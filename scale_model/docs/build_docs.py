import os
import sys
from sphinx.cmd.build import main as sphinx_build

if __name__ == "__main__":
    # Get the directory containing this script
    docs_dir = os.path.dirname(os.path.abspath(__file__))

    # Change to the docs directory
    os.chdir(docs_dir)

    # Add the project root to the Python path
    sys.path.insert(0, os.path.abspath(".."))

    # Run Sphinx build
    sphinx_build(["-b", "html", ".", "_build/html"])
