"""
Worker de fond EHPAD.

Ce process separe les traitements lents du backend API. Il ne sert pas HTTP:
il genere les rapports LLM quotidiens et les stocke dans Redis.
"""

import logging

from main import daily_llm_report_loop


logging.basicConfig(level=logging.INFO, format="%(asctime)s [LLM_WORKER] %(message)s")
log = logging.getLogger(__name__)


if __name__ == "__main__":
    log.info("Worker LLM quotidien demarre")
    daily_llm_report_loop()
