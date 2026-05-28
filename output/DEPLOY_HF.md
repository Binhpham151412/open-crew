# Deploy OpenCrew to Hugging Face Spaces

## Prerequisites

1. **Hugging Face account** — Sign up at https://huggingface.co
2. **Hugging Face CLI** — Install with:
   ```bash
   pip install huggingface_hub
   ```
3. **Login** — Run:
   ```bash
   huggingface-cli login
   ```

## Quick Deploy (Windows)

```bash
cd output
deploy-hf.bat
```

## Manual Deploy

### Step 1: Create a new Space

1. Go to https://huggingface.co/new-space
2. Choose:
   - **Name**: `opencrew` (or any name)
   - **SDK**: `Docker`
   - **Hardware**: `CPU Basic` (free tier - 2 vCPU, 16GB RAM)
   - **Visibility**: `Public` or `Private`

### Step 2: Clone the Space

```bash
git clone https://huggingface.co/spaces/YOUR_USERNAME/opencrew
cd opencrew
```

### Step 3: Copy OpenCrew files

```bash
# Copy these files from output/
cp -r ../output/shared ./
cp -r ../output/agents ./
cp -r ../output/web ./
cp ../output/Dockerfile.hf ./Dockerfile
cp ../output/supervisord.conf ./
cp ../output/start.sh ./
cp ../output/README_hf.md ./README.md
```

### Step 4: Push to Hugging Face

```bash
git add .
git commit -m "Deploy OpenCrew"
git push
```

### Step 5: Set Environment Variables

In your Space page → **Settings** → **Variables and secrets** → **New secret**:

| Name | Value | Required |
|---|---|---|
| `MIMO_API_KEY` | `YOUR_MIMO_API_KEY` | Yes |
| `MIMO_BASE_URL` | `https://token-plan-sgp.xiaomimimo.com/v1` | No |
| `MIMO_MODEL` | `mimo-v2.5-pro` | No |
| `GITHUB_TOKEN` | `YOUR_GITHUB_TOKEN` | No |

### Step 6: Wait for Build

- HF will build the Docker image (takes 5-10 minutes)
- Watch the build logs in the Space page
- Once ready, you'll see the app at: `https://YOUR_USERNAME-opencrew.hf.space`

## Access Your Space

- **Direct URL**: `https://YOUR_USERNAME-opencrew.hf.space`
- **HF Page**: `https://huggingface.co/spaces/YOUR_USERNAME/opencrew`

## Troubleshooting

### Build fails
- Check build logs in Space page
- Ensure all files are copied correctly
- Verify Dockerfile syntax

### App doesn't start
- Check Space logs (Settings → Logs)
- Verify MIMO_API_KEY is set correctly
- Wait 2-3 minutes for all services to start

### Agents not responding
- Check if Redis is running (Space logs)
- Verify agent health at: `https://YOUR_USERNAME-opencrew.hf.space/api/agents`
- Check individual agent logs in Space logs

### Memory issues
- Free tier has 16GB RAM - should be enough
- If OOM, try reducing agent count or using smaller models

## Limitations

- **Free tier**: 2 vCPU, 16GB RAM — enough for demo
- **Sleep**: Free Spaces sleep after 48h of inactivity
- **Build time**: 5-10 minutes for initial build
- **Single container**: All services in one container (for simplicity)

## Production Use

For production, consider:
- **Persistent storage**: Add HF Persistent Storage for Redis data
- **Upgrade hardware**: Use GPU or better CPU for faster inference
- **Custom domain**: Set up custom domain in Space settings
- **Monitoring**: Add external monitoring (Uptime Robot, etc.)
