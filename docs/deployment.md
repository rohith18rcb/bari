# Deploying BARI to a permanent, free URL (Render.com)

The dashboard can run two ways:

1. **Locally + a tunnel** (`cloudflared tunnel --url http://localhost:8000`)
   — fastest to start, free, no account, but the URL is random and only
   works while your machine is on. See the main README's "Public
   deployment" section.
2. **A real free-tier cloud deployment** (this document) — a fixed URL like
   `https://bari.onrender.com` that works even when your laptop is off.

## Deploy in one click

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/rohith18rcb/bari)

1. Click the button above (or go to render.com → New → Blueprint → point it
   at this GitHub repo).
2. Sign in / create a free Render account (no credit card required for the
   free tier).
3. Render reads `render.yaml` at the repo root and provisions everything
   automatically — build command, start command, and environment variables
   are already configured.
4. First build takes a few minutes (installing PyTorch + Ultralytics from
   scratch). Once it's live, your URL is `https://<service-name>.onrender.com`.

## What's different from running it locally

- **Detection works out of the box** — the trained model
  (`ml/models/pothole_yolo_best.pt`) is committed to the repo specifically
  so the deployed service has something to run inference with, without
  requiring a training step during deploy.
- **The free tier sleeps after 15 minutes of no traffic** and takes
  ~30-50 seconds to wake back up on the next request. This is a Render
  free-tier characteristic, not a bug in BARI.
- **Disk is ephemeral** — the SQLite database and evidence images reset on
  every redeploy (and may reset on a restart after sleep, depending on
  Render's current free-tier disk policy). This deployment is meant to
  demonstrate the live pipeline, not to be a permanent data store. For
  durable storage, upgrade to a Render paid plan with a persistent disk, or
  point `DATABASE_PATH`/`EVIDENCE_PATH` at an external volume/object store.
- **CPU-only, shared free-tier compute** — inference will be slower than on
  a dedicated machine; fine for occasional demo use, not for high-throughput
  capture.
- **The native Android app and browser capture page both work against a
  Render deployment** the same way they work against a local server — just
  set the server address to your `https://<service-name>.onrender.com` URL
  instead of a local IP. No app-side code changes needed.

## Updating the deployment

Render auto-deploys on every push to `master` (configurable in the Render
dashboard). To ship a newly retrained model, copy the new best checkpoint
over `ml/models/pothole_yolo_best.pt`, commit, and push:

```bash
cp ml/training/runs/pothole_yolo/weights/best.pt ml/models/pothole_yolo_best.pt
git add ml/models/pothole_yolo_best.pt
git commit -m "Update deployed model weights"
git push
```
