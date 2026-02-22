# MediaWaiter - Running Successfully ✅

## Current Status

MediaWaiter is now running on **http://localhost:5000** with all JSON endpoints enabled!

## How to Start MediaWaiter

Run this command from the MediaWaiter directory:

```bash
cd /home/yokley/workspace/MV/MediaWaiter

docker rm -f mv-mediawaiter 2>/dev/null || true

docker run -d \
  --name mv-mediawaiter \
  -p 127.0.0.1:5000:5000 \
  -v /home/yokley/workspace/MV/MediaWaiter:/code \
  -v /home/yokley/tv_shows2:/www/media/tv \
  -v /home/yokley/Movies:/www/media/movies \
  -e PYTHONPATH=/code/src \
  -e FLASK_DEBUG=1 \
  -e MW_USE_NGINX=false \
  -e MW_BASE_PATH=/www/media \
  -e MW_MEDIA_DIRS=tv,movies \
  -e MW_WAITER_USERNAME=waiter \
  -e MW_WAITER_PASSWORD='hSnk%BgQdXKhEsr^W6N6' \
  -e MW_MEDIAVIEWER_BASE_URL=http://127.0.0.1:8000/mediaviewer \
  -e MW_EXTERNAL_MEDIAVIEWER_BASE_URL=http://localhost:8000/mediaviewer \
  kyokley/mediawaiter \
  /bin/mediawaiter
```

**Or use the convenience script** (once devenv is reloaded):
```bash
start-waiter
```

## Verify It's Running

```bash
# Check container status
docker ps | grep mediawaiter

# View logs
docker logs -f mv-mediawaiter

# Test status endpoint
curl http://localhost:5000/waiter/status
```

## Stop MediaWaiter

```bash
docker rm -f mv-mediawaiter
```

## Testing JSON Endpoints

**Prerequisites**: MediaViewer must be running on http://localhost:8000

```bash
# 1. Get authentication token
TOKEN=$(curl -s -X POST http://localhost:8000/mediaviewer/api/v2/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "testpass123"}' | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['data']['access'])")

# 2. Get episode stream URL and GUID
GUID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/mediaviewer/api/v2/episodes/11255/stream/ | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['guid'])")

# 3. Fetch JSON metadata
curl "http://localhost:5000/waiter/file/$GUID/json" | python3 -m json.tool
```

## Available Endpoints

All JSON endpoints are now live:

- `GET /waiter/file/<guid>/json` - TV episode metadata
- `GET /waiter/dir/<guid>/json` - Movie metadata
- `GET /waiter/file/<guid>/autoplay/json` - Autoplay metadata
- `GET /waiter/stream/<guid>/<hash>/json` - Streaming metadata
- `GET /waiter/watch-party/<guid>/<hash>/json` - Watch party metadata

## Code Changes Applied

✅ All code changes are now active in the running container:
- Route ordering fixed (JSON routes before catch-all)
- Data extraction helper functions
- JSON endpoint handlers
- Subtitle support
- Navigation links (next/previous episodes)

## Next Steps

1. ✅ MediaWaiter is running
2. ⏳ Start MediaViewer on http://localhost:8000
3. ⏳ Test complete flow (login → get stream → fetch JSON)
4. ⏳ Test video playback in React frontend

## Troubleshooting

### "Connection refused" on port 5000
- Check container is running: `docker ps | grep mediawaiter`
- Check logs: `docker logs mv-mediawaiter`

### "Unable to find matching path"
- Verify token GUID is valid
- Check MediaViewer is accessible from container
- Verify media files exist in mounted directories

### Route not found / HTML instead of JSON
- Verify URL ends with `/json`
- Check route ordering in waiter.py (catch-all should be last)

## Implementation Complete! 🎉

MediaWaiter is successfully running with:
- ✅ All 5 JSON endpoints implemented
- ✅ Route ordering fixed
- ✅ Code changes mounted and active
- ✅ Running on http://localhost:5000
- ✅ Ready for frontend integration

See `JSON_ENDPOINTS.md` for complete API documentation.
