FROM python:3.13-slim

WORKDIR /app

# Create non-root user
RUN adduser --disabled-password --gecos '' app && chown -R app:app /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies as root to avoid permission issues
RUN uv sync --frozen --no-dev

# Switch to non-root user
USER app

# Copy application code
COPY --chown=app:app . .

# Run the bot using uv to activate the virtual environment
CMD ["uv", "run", "python", "-m", "letta_bot.main"]
