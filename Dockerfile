# Use Python 3.9 slim as base image
FROM python:3.9-slim

# Install system dependencies required for OpenCV
#RUN apt-get update && apt-get install -y \
#    libglib2.0-0 \
#    libsm6 \
#    libxext6 \
#    libxrender-dev \
#    libgl1-mesa-glx \
#    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose port 5000 (assuming Flask will be used)
EXPOSE 5000

# Command to run the application
CMD ["python", "app.py"] 