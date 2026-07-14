"""Standalone entrypoint for the IMAP ingestion poll loop.

Run as its own process/container (the `ingest-worker` docker-compose
service) rather than an in-process asyncio task inside the API
process, so a stuck IMAP connection can't affect API responsiveness
and the two can be restarted/scaled independently.
"""
import asyncio
import logging

from app.services.email_ingest import email_poll_loop

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(email_poll_loop())
