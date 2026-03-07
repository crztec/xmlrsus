FROM python:3.9-slim

# Install system dependencies
# - wget and gnupg are needed to fetch browser binaries securely
# - chromium is the open-source base for Google Chrome, fully supported by Google Cloud
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    chromium \
    chromium-driver \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the default Streamlit port (8501) or map it to Cloud Run's required $PORT
EXPOSE 8080

# Configure Streamlit settings to run smoothly in a container environment
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
ENV STREAMLIT_SERVER_PORT=8080
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Limit upload size to 10MB
ENV STREAMLIT_SERVER_MAX_UPLOAD_SIZE=10

# Configure Xvfb so Chrome thinks there is a real screen attached
ENV DISPLAY=:99

# Start Streamlit application wrapped inside Xvfb virtual display
CMD ["xvfb-run", "-s", "-screen 0 1920x1080x24", "streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0", "--server.maxUploadSize=10"]
