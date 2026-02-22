# MediaWaiter JSON Endpoints - Correct Usage for VideoPlayer

## Flow for Getting Video URL

### Step 1: MediaViewer Generates Download Token

**Endpoint:** `GET /api/v2/episodes/{episode_id}/stream/`

MediaViewer creates a download token with a GUID and returns:

```json
{
  "stream_url": "localhost:5000/waiter/file/{guid}/",
  "episode_id": 11255,
  "episode_name": "S04 E01: Identity Theft",
  "guid": "abc123..."
}
```

### Step 2: Frontend Calls MediaWaiter Autoplay JSON Endpoint

**Endpoint:** `GET /waiter/file/{guid}/autoplay/json`

Using the GUID from step 1, the frontend requests the autoplay JSON metadata:

```bash
curl http://localhost:5000/waiter/file/abc123.../autoplay/json
```

**Response:**
```json
{
  "title": "S04 E01: Identity Theft",
  "filename": "Slow.Horses.S04E01.mkv",
  "video_file": "/waiter/file/abc123.../hashed_video_path",
  "subtitle_files": ["/path/to/subtitle.srt"],
  "hashPath": "hashed_video_path",
  "next_link": "http://localhost:8000/mediaviewer/autoplaydownloadlink/11256/",
  "previous_link": null,
  "tv_id": 404,
  "tv_name": "Slow Horses",
  "ismovie": false,
  "binge_mode": true,
  "CAST_ID": "{google_cast_app_id}",
  "files": [...],
  "watch_party_url": ""
}
```

### Step 3: Frontend Uses video_file for Playback

The `video_file` field contains the direct video URL to use in the `<video>` element:

```typescript
<video src={metadata.video_file} controls>
  {metadata?.subtitle_files?.map((subtitle, i) => (
    <track key={i} src={subtitle} kind="subtitles" />
  ))}
</video>
```

## Why Autoplay JSON?

The `/autoplay/json` endpoint is specifically designed for video player data:

1. **Returns `video_file`** - Direct video URL for playback
2. **Includes `subtitle_files`** - Array of subtitle paths
3. **Provides navigation** - `next_link` and `previous_link` for binge mode
4. **Video player metadata** - All data needed for the video player UI
5. **Watch party support** - Optional Jitsi integration URL

## Comparison of Endpoints

### `/waiter/file/{guid}/json` (File Listing)
- **Purpose**: Display list of video files in directory
- **Returns**: Array of `files` with multiple videos
- **Use case**: Directory browsing, file selection
- **Not ideal for**: Direct playback (no single video_file)

### `/waiter/file/{guid}/autoplay/json` ✅ (Video Player)
- **Purpose**: Get video player data for direct playback
- **Returns**: Single `video_file` URL ready for `<video>` element
- **Use case**: Immediate video playback, autoplay next episode
- **Perfect for**: VideoPlayer component

## Implementation in useEpisodeStream Hook

```typescript
// Step 1: Get stream URL with GUID from MediaViewer
const response = await apiClient.get(`/episodes/${episodeId}/stream/`)

// Step 2: Build autoplay JSON URL
const baseUrl = `http://${response.data.stream_url}`
const jsonUrl = `${baseUrl}/autoplay/json`

// Step 3: Fetch metadata
const metadataResponse = await fetch(jsonUrl)
const metadata = await metadataResponse.json()

// Step 4: Extract video URL
const videoUrl = metadata.video_file

// Step 5: Use in VideoPlayer
<video src={videoUrl} />
```

## Complete Test Flow

```bash
# 1. Login to MediaViewer
TOKEN=$(curl -s -X POST http://localhost:8000/mediaviewer/api/v2/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "testpass123"}' | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['data']['access'])")

# 2. Get episode stream (creates download token)
STREAM=$(curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/mediaviewer/api/v2/episodes/11255/stream/)

echo "Stream data:"
echo "$STREAM" | python3 -m json.tool

# 3. Extract GUID
GUID=$(echo "$STREAM" | python3 -c "import sys, json; print(json.load(sys.stdin)['guid'])")

# 4. Call autoplay JSON endpoint
echo -e "\nAutoplay metadata:"
curl -s "http://localhost:5000/waiter/file/$GUID/autoplay/json" | python3 -m json.tool

# 5. Extract video_file
VIDEO_URL=$(curl -s "http://localhost:5000/waiter/file/$GUID/autoplay/json" | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['video_file'])")

echo -e "\nDirect video URL: $VIDEO_URL"

# 6. Test video file is accessible
curl -I "http://localhost:5000$VIDEO_URL" | head -10
```

## MediaWaiter Must Be Running

Ensure MediaWaiter is running with the updated code:

```bash
docker ps | grep mediawaiter

# Should show:
# mv-mediawaiter   kyokley/mediawaiter   "/bin/mediawaiter"   Up X minutes   127.0.0.1:5000->5000/tcp
```

If not running:

```bash
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
  kyokley/mediawaiter \
  /bin/mediawaiter
```

## Summary

✅ **Correct endpoint**: `/waiter/file/{guid}/autoplay/json`
✅ **Returns**: `video_file` field with direct video URL
✅ **Frontend updated**: `useEpisodeStream` now uses autoplay endpoint
✅ **Build successful**: No TypeScript errors
✅ **Ready for testing**: MediaWaiter is running on port 5000

Next step: Start MediaViewer and test the complete flow!
