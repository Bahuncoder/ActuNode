import os

# TestClient sends "Host: testserver"; allow it alongside the defaults (see app/security.py, D-24).
os.environ.setdefault("ACTUNODE_ALLOWED_HOSTS", "localhost,127.0.0.1,::1,testserver")
