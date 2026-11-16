"""Patterns shared by check_clean.py (to flag) and scrub.py (to redact)."""
import re

API_KEY = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{10,}|\bsk-[A-Za-z0-9_-]{20,}|\b[sr]k_live_[A-Za-z0-9]{16,}|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|\bglpat-[A-Za-z0-9_-]{20,}|"
    r"\bAKIA[0-9A-Z]{16}\b|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bhf_[A-Za-z0-9]{30,}|\bAIza[0-9A-Za-z_-]{35}|"
    r"\bgsk_[A-Za-z0-9]{20,}|\br8_[A-Za-z0-9]{20,}|\bnpm_[A-Za-z0-9]{30,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
