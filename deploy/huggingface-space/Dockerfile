FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/home/user/.cache/uv

RUN useradd --create-home --uid 1000 user

USER user
WORKDIR /home/user/app

COPY --chown=user:user start-agentfinder.sh /home/user/app/start-agentfinder.sh
RUN chmod +x /home/user/app/start-agentfinder.sh

EXPOSE 7860

CMD ["/home/user/app/start-agentfinder.sh"]
