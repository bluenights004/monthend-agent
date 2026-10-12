"""Frozen inputs for one run, with SHA-256 hashes of every file."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from monthend.sources.xero_parse import TBLine, parse_budgets, parse_trial_balance

CANONICAL = ("organisation.json", "accounts.json", "trial-balance-current.json", "trial-balance-prior.json",
             "budgets.json", "invoices.json", "bank-transactions.json", "messages.json")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Document:
    doc_id: str
    filename: str
    path: Path
    sha256: str
    media_type: str

    @property
    def short_hash(self) -> str:
        return self.sha256[:12]


@dataclass
class SourceBundle:
    organisation: dict
    accounts: list[dict]
    tb_current: list[TBLine]
    tb_prior: list[TBLine]
    budgets: dict[str, dict[str, Decimal]]
    invoices: list[dict]
    bank_transactions: list[dict]
    messages: list[dict]
    documents: dict[str, Document] = field(default_factory=dict)

    def document_by_filename(self, filename: str) -> Document | None:
        return next((d for d in self.documents.values() if d.filename == filename), None)


def write_inputs_manifest(inputs_dir: Path) -> dict:
    files = {}
    for path in sorted(inputs_dir.rglob("*")):
        if path.is_file() and path.name != "inputs-manifest.json":
            files[path.relative_to(inputs_dir).as_posix()] = sha256_file(path)
    missing = [name for name in CANONICAL if name not in files]
    if missing:
        raise FileNotFoundError(f"snapshot is incomplete, missing: {', '.join(missing)}")
    manifest = {"files": files, "inputs_sha256": sha256_json(files)}
    (inputs_dir / "inputs-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify_inputs(inputs_dir: Path) -> list[str]:
    """Return a list of files whose content no longer matches the manifest."""
    manifest = json.loads((inputs_dir / "inputs-manifest.json").read_text())
    problems = []
    for rel, expected in manifest["files"].items():
        path = inputs_dir / rel
        if not path.exists():
            problems.append(f"{rel}: missing")
        elif sha256_file(path) != expected:
            problems.append(f"{rel}: changed since snapshot")
    return problems


def load_bundle(inputs_dir: Path) -> SourceBundle:
    def read(name: str) -> dict:
        return json.loads((inputs_dir / name).read_text())

    documents = {}
    doc_dir = inputs_dir / "documents"
    if doc_dir.exists():
        for path in sorted(doc_dir.iterdir()):
            if path.is_file():
                doc = Document(doc_id=path.stem, filename=path.name, path=path, sha256=sha256_file(path),
                               media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                documents[doc.doc_id] = doc
    return SourceBundle(
        organisation=read("organisation.json").get("Organisations", [{}])[0],
        accounts=read("accounts.json").get("Accounts", []),
        tb_current=parse_trial_balance(read("trial-balance-current.json")),
        tb_prior=parse_trial_balance(read("trial-balance-prior.json")),
        budgets=parse_budgets(read("budgets.json")),
        invoices=read("invoices.json").get("Invoices", []),
        bank_transactions=read("bank-transactions.json").get("BankTransactions", []),
        messages=read("messages.json").get("value", []),
        documents=documents,
    )
