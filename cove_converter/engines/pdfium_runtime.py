"""Process-wide coordination for pypdfium2 native object lifetimes."""
from __future__ import annotations

import threading


# PDFium keeps process-global native state and is not safe to use from the
# converter's parallel worker threads.  Every PdfDocument lifetime, including
# validation documents, must be contained by this one lock.
PDFIUM_LOCK = threading.RLock()
