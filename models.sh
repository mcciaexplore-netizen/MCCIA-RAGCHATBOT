#!/bin/bash
cd ~/Desktop/MCCIA-Google/sampada
source .venv/bin/activate

case "$1" in
  paddle)
    python3 -m mlx_vlm.server --model PaddlePaddle/PaddleOCR-VL-1.6 --port 8111
    ;;
  qwen)
    python3 -m mlx_vlm.server --model mlx-community/Qwen3-VL-8B-Instruct-4bit --port 8112
    ;;
  gemma)
    python3 -m mlx_vlm.server --model mlx-community/gemma-4-e4b-it-4bit --port 8113
    ;;
  stop)
    pkill -f mlx_vlm.server && echo "All servers stopped"
    ;;
  status)
    for p in 8111 8112 8113; do
      curl -s -m 2 http://localhost:$p/v1/models > /dev/null \
        && echo "$p: running" || echo "$p: down"
    done
    ;;
  *)
    echo "usage: ./models.sh [paddle|qwen|gemma|stop|status]"
    ;;
esac