# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — WhatsApp RPA Automator (Render.com deployment)
#
# Build:  docker build -t whatsapp-rpa .
# Run:    docker run -p 10000:10000 -e PORT=10000 whatsapp-rpa
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# ── 1. System dependencies ────────────────────────────────────────────────────
# Xvfb   : virtual display so Chrome renders without a real screen
# xclip  : clipboard support for pyperclip on Linux
# fonts  : prevent Chrome font rendering crashes
# libX*  : Chrome GUI libs needed even in Xvfb mode
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg curl ca-certificates \
    xvfb xclip \
    fonts-liberation fonts-noto-color-emoji libfontconfig1 \
    libx11-6 libxcomposite1 libxcursor1 libxdamage1 libxext6 \
    libxfixes3 libxi6 libxrandr2 libxrender1 libxss1 libxtst6 \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libdrm2 libxkbcommon0 libgbm1 libasound2 libxshmfence1 \
    libpangocairo-1.0-0 libpango-1.0-0 libcairo2 \
    procps \
    && rm -rf /var/lib/apt/lists/*

# ── 2. Install Google Chrome stable ──────────────────────────────────────────
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor > /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
       http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# ── 3. App setup ──────────────────────────────────────────────────────────────
WORKDIR /app

# Install Python dependencies first (layer-cached separately from app code)
COPY requirements_render.txt .
RUN pip install --no-cache-dir -r requirements_render.txt

# Copy application code
COPY . .

# Create runtime directories (writable by the app)
RUN mkdir -p uploads reports logs browser_profiles

# ── 4. Environment ────────────────────────────────────────────────────────────
ENV DISPLAY=:99 \
    PYTHON_ENV=production \
    DBUS_SESSION_BUS_ADDRESS=/dev/null \
    # Suppress webdriver-manager download noise
    WDM_LOG=0 \
    WDM_LOG_LEVEL=0

# Render assigns PORT dynamically (default 10000)
EXPOSE 10000

# ── 5. Start command ──────────────────────────────────────────────────────────
# 1. Start Xvfb virtual display on :99  (1280x900, 24-bit color)
# 2. Wait 1 second for Xvfb to be ready
# 3. Start gunicorn with eventlet worker for SocketIO
CMD rm -f /tmp/.X99-lock && \
    Xvfb :99 -screen 0 1280x900x24 -ac +extension GLX +render -noreset & \
    sleep 1 && \
    exec gunicorn \
        --worker-class eventlet \
        -w 1 \
        --bind "0.0.0.0:${PORT:-10000}" \
        --timeout 300 \
        --keep-alive 5 \
        --log-level info \
        web_app:app
