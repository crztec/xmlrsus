FROM python:3.9-slim

# Install system dependencies
# - wget and gnupg are needed to fetch Firefox binaries securely
# - firefox-esr is the stable Extended Support Release version of Firefox for Linux
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    firefox-esr \
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

# Start Streamlit application
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]
