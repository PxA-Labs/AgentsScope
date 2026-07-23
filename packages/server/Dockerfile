FROM python:3.10-slim

WORKDIR /app

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create directory for persistent SQLite data and configure system user
RUN mkdir -p /app/data && \
    groupadd -g 1001 agentscope && \
    useradd -u 1001 -g agentscope -s /bin/sh agentscope && \
    chown -R agentscope:agentscope /app/data

USER agentscope

EXPOSE 8765

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765"]
