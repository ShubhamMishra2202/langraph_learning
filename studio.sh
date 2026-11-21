#!/usr/bin/env bash
# Start the LangGraph dev server and open LangGraph Studio for the graph in langgraph.json.
#
# The dev server (langgraph-api) needs Python >= 3.11 and venv/ is 3.10, so uvx builds a
# separate cached 3.11 env with the CLI plus requirements.txt. venv/ is still what main.py uses.
#
#   ./studio.sh                 # opens https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
#   ./studio.sh --no-browser    # any extra flags go to `langgraph dev`
set -euo pipefail
cd "$(dirname "$0")"
exec uvx --python 3.11 --from "langgraph-cli[inmem]" --with-requirements requirements.txt \
    langgraph dev "$@"
