# EcoWatt Vision – AI Spatial Energy & Bill Optimizer

EcoWatt Vision turns a room or office photo into a visual energy audit, identifying visible appliances and estimating their monthly electricity use. It combines Gemini 2.5 Flash vision with practical, appliance-specific recommendations and a Pakistan-rupee bill estimate based on an assumed tariff of PKR 55 per kWh. An interactive dashboard visualizes efficiency and consumption, while a runtime-reduction simulator estimates potential monthly and annual savings.

## Features

- Upload or drag and drop a JPEG, PNG, or WebP room photo.
- Gemini 2.5 Flash image analysis constrained to a structured JSON response.
- Demo-safe fallback data when the API key is missing or the Gemini request fails.
- KPI cards for appliance count, monthly kWh, and estimated PKR bill.
- Semi-circle efficiency gauge and per-appliance monthly consumption chart.
- Color-coded appliance optimization directives and a live bill savings simulator.
- Image upload size and format validation; the API key is read from the environment.

## Local setup

Requires Python 3.10 or newer.

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Optionally set your Gemini API key. Without it, the app uses realistic demo analysis:

   ```powershell
   $env:GEMINI_API_KEY = "your-google-ai-studio-api-key"
   ```

4. Start the development server:

   ```powershell
   python app.py
   ```

5. Open [http://localhost:5000](http://localhost:5000).

The `GEMINI_API_KEY` is optional for a working demo. `PORT` defaults to `5000`; set it in the environment when needed. Set `FLASK_DEBUG=true` only for local development.

## Deployment

### Render

1. Push the project to a GitHub repository and create a new Render **Web Service** connected to it.
2. Set **Build Command** to `pip install -r requirements.txt`.
3. Set **Start Command** to `gunicorn app:app`.
4. Add `GEMINI_API_KEY` as a secret environment variable in the Render dashboard. The service listens on the `PORT` provided by the host. If the key is not configured, the app remains usable with demo data.

### Railway

1. Create a Railway project from the GitHub repository.
2. Set the start command to `gunicorn app:app` if it is not detected automatically.
3. Add `GEMINI_API_KEY` in the service's Variables settings. Railway provides `PORT`; the app reads it automatically.

### Vercel

This repository is a Flask WSGI application and is not a native Vercel static-site deployment. Use Render or Railway for the included deployment-ready setup, or add and maintain an appropriate Python serverless adapter before deploying to Vercel.

## API

`POST /analyze` accepts `multipart/form-data` with an `image` field containing one supported image. Successful requests return the efficiency score, detected appliances, optimization directives, total monthly kWh, projected monthly PKR bill, tariff, and whether the result came from Gemini or the demo fallback. Invalid uploads return a JSON error with an appropriate 4xx status.

## Estimate notes

Energy usage and efficiency are estimates inferred from a photo, not measured readings. The simulator applies the selected daily runtime reduction to the combined rated power of detected heavy appliances; actual appliance behavior, usage, and utility tariffs can change real savings.
