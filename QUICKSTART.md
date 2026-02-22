# MediaWaiter JSON Endpoints - Quick Start Guide

## Running MediaWaiter

```bash
cd /home/yokley/workspace/MV/MediaWaiter
up
```

This starts MediaWaiter on `http://127.0.0.1:5000` with all JSON endpoints enabled.

## Available JSON Endpoints

| Endpoint | Description | Example |
|----------|-------------|---------|
| `GET /waiter/file/<guid>/json` | TV episode metadata | Returns video_file, subtitles, navigation |
| `GET /waiter/dir/<guid>/json` | Movie metadata | Returns file list, collections, genres |
| `GET /waiter/file/<guid>/autoplay/json` | Autoplay metadata | Video player data for autoplay mode |
| `GET /waiter/stream/<guid>/<hash>/json` | Streaming metadata | Direct stream player data |
| `GET /waiter/watch-party/<guid>/<hash>/json` | Watch party metadata | Includes Jitsi integration data |

## Quick Test

```bash
# 1. Get auth token
TOKEN=$(curl -s -X POST http://localhost:8000/mediaviewer/api/v2/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "testpass123"}' | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['data']['access'])")

# 2. Get episode stream (Slow Horses S04E01)
GUID=$(curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/mediaviewer/api/v2/episodes/11255/stream/ | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['guid'])")

# 3. Fetch JSON metadata
curl "http://localhost:5000/waiter/file/$GUID/json" | python3 -m json.tool
```

## Frontend Usage

```typescript
import { useEpisodeStream } from '../hooks/useTV'

function MyPlayer({ episodeId }: { episodeId: number }) {
  const { streamUrl, metadata, isLoading, error } = useEpisodeStream(episodeId)

  if (isLoading) return <div>Loading...</div>
  if (error) return <div>Error: {error}</div>

  return (
    <video src={streamUrl} controls>
      {metadata?.subtitle_files?.map((subtitle, i) => (
        <track key={i} src={subtitle} kind="subtitles" />
      ))}
    </video>
  )
}
```

## JSON Response Example

```json
{
  "title": "S04 E01: Identity Theft",
  "filename": "Slow.Horses.S04E01.mkv",
  "video_file": "/waiter/file/{guid}/4a3c2b1d...",
  "subtitle_files": ["/path/to/subtitle.srt"],
  "hashPath": "4a3c2b1d...",
  "files": [
    {
      "path": "/waiter/file/{guid}/4a3c2b1d...",
      "hashedWaiterPath": "4a3c2b1d...",
      "subtitleFiles": []
    }
  ],
  "next_link": "http://localhost:8000/mediaviewer/autoplaydownloadlink/11256/",
  "previous_link": null,
  "tv_id": 404,
  "tv_name": "Slow Horses",
  "ismovie": false,
  "binge_mode": true,
  "mediaviewer_base_url": "http://localhost:8000/mediaviewer",
  "guid": "{guid}",
  "username": "testuser"
}
```

## Important Notes

### Route Ordering
The catch-all route `/file/<guid>/<path:hashPath>` must be defined AFTER specific routes like `/file/<guid>/json`. This is already configured correctly in `waiter.py`.

### Environment Variables
The `up` script automatically sets all required environment variables:
- Media paths point to `/home/yokley/tv_shows2` and `/home/yokley/Movies`
- Authentication configured for user `waiter`
- URLs configured for local development

### CORS
If running frontend on different port/domain, you may need to add CORS headers to MediaWaiter responses.

## Troubleshooting

### "Unable to find matching path"
- Check that the token GUID is valid
- Verify MediaViewer is running and accessible
- Check that the file exists in the media directory

### "KeyError: 'isvalid'"
- MediaViewer password hash must match MediaWaiter password
- Set `MV_WAITER_PASSWORD_HASH` environment variable in MediaViewer

### JSON endpoint returns HTML
- Route ordering issue - check that JSON routes are defined before catch-all
- Verify you're accessing the correct URL (should end with `/json`)

### Port 5000 already in use
- Stop any existing MediaWaiter Docker containers: `docker rm -f mv-mediawaiter`
- Check for other processes: `ss -tlnp | grep :5000`

## Files Changed

- ✅ MediaWaiter: `src/mediawaiter/waiter.py` (JSON endpoints)
- ✅ MediaWaiter: `devenv.nix` ("up" script)
- ✅ MediaViewer: `mediaviewer/api/v2/media_views.py` (stream endpoint)
- ✅ MediaViewer: `mediaviewer/api/v2/urls.py` (URL route)
- ✅ Frontend: `frontend/src/hooks/useTV.ts` (useEpisodeStream hook)
- ✅ Frontend: `frontend/src/components/VideoPlayer.tsx` (metadata integration)

## Documentation

- `JSON_ENDPOINTS.md` - Complete API documentation
- `IMPLEMENTATION_SUMMARY.md` - Full implementation details
- `QUICKSTART.md` - This file

## Next Steps

1. Start MediaWaiter: `cd /home/yokley/workspace/MV/MediaWaiter && up`
2. Verify backend running: `curl http://localhost:5000/waiter/status`
3. Test JSON endpoint with script above
4. Open frontend: `http://localhost:3000`
5. Test video playback in browser

---

**Questions?** See `JSON_ENDPOINTS.md` for detailed API documentation or `IMPLEMENTATION_SUMMARY.md` for architecture details.
