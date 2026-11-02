"""Compara a silver (extração do LLM) com os gabaritos em evaluation/gabarito/*.json.

Uso:  python scripts/evaluate_extraction.py [--model gpt-4.1-mini] [--prompt v2]
Saída: relatório no terminal + linhas em editais_silver.extraction_eval (histórico por versão).
A DAG silver_editais roda a mesma avaliação para a versão atual; aqui é para comparar versões à mão.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from editais.extraction_eval import run_evaluation  # noqa: E402
from editais.llm_extraction import PROMPT_VERSION, default_model  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=default_model())
    ap.add_argument("--prompt", default=PROMPT_VERSION)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    gabaritos = Path(__file__).resolve().parents[1] / "evaluation/gabarito"
    run_evaluation(args.model, args.prompt, gabaritos, save=not args.no_save)


if __name__ == "__main__":
    os.environ.setdefault("GCP_PROJECT_ID", "")
    main()
