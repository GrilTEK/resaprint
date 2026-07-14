from pydantic import BaseModel


class ConfigOut(BaseModel):
    imap_host: str | None
    imap_port: int
    imap_user: str | None
    imap_has_password: bool  # never expose the decrypted password over the API
    imap_folder: str
    imap_processed_folder: str
    imap_poll_seconds: int


class ConfigUpdate(BaseModel):
    imap_host: str | None = None
    imap_port: int | None = None
    imap_user: str | None = None
    imap_password: str | None = None  # write-only; omit or blank = leave unchanged
    imap_folder: str | None = None
    imap_processed_folder: str | None = None
    imap_poll_seconds: int | None = None
