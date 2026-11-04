# -*- mode: python ; coding: utf-8 -*-
# Legacy (PyQt5) build: the same spec as PSPify.spec with PSPIFY_QT=5.
# Run it from a Python environment that has PyQt5 installed (requirements-pyqt5.txt).
import os

os.environ["PSPIFY_QT"] = "5"
exec(compile(open(os.path.join(SPECPATH, "PSPify.spec"), encoding="utf-8").read(), "PSPify.spec", "exec"))
