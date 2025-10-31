"""Utility helpers to manage OpenAI Vector Stores for the advisor workflow."""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Iterable

from openai import OpenAI


def create_vector_store(client: OpenAI, name: str) -> str:
    response = client.vector_stores.create(name=name)
    return response.id


def upload_files(client: OpenAI, store_id: str, files: Iterable[pathlib.Path]) -> None:
    for path in files:
        with path.open("rb") as fh:
            client.vector_stores.files.upload(
                vector_store_id=store_id,
                file=fh,
            )


def list_files(client: OpenAI, store_id: str):
    return client.vector_stores.files.list(vector_store_id=store_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage OpenAI Vector Store assets.")
    parser.add_argument("--name", help="Vector store name (when creating).")
    parser.add_argument("--store-id", help="Existing vector store id.")
    parser.add_argument("--upload", nargs="*", type=pathlib.Path, help="File paths to upload.")
    args = parser.parse_args()

    client = OpenAI()

    store_id = args.store_id
    if not store_id:
        if not args.name:
            raise SystemExit("Either --store-id or --name must be provided.")
        store_id = create_vector_store(client, args.name)
        print(f"Created vector store: {store_id}")

    if args.upload:
        upload_files(client, store_id, args.upload)
        print(f"Uploaded {len(args.upload)} files to {store_id}")

    files = list_files(client, store_id)
    print(json.dumps([item.dict() for item in files.data], indent=2))


if __name__ == "__main__":
    main()
