# MediaWaiter JSON API Endpoints

This document describes the new JSON API endpoints added to MediaWaiter for programmatic access to video metadata.

## Overview

MediaWaiter now provides JSON endpoints that return the same data used by the HTML templates, allowing frontend applications to access video metadata directly without parsing HTML.

## New Endpoints

### 1. TV Episode File Listing - `/waiter/file/<guid>/json`

Returns metadata for a TV episode file listing.

**Example Request:**
```bash
curl http://localhost:5000/waiter/file/{guid}/json
```

**Response:**
```json
{
  "title": "S04 E01: Identity Theft",
  "filename": "Slow.Horses.S04E01.mkv",
  "files": [
    {
      "path": "/waiter/file/{guid}/{hashed_path}",
      "hashedWaiterPath": "{hashed_path}",
      "subtitleFiles": [
        {"waiter_path": "/path/to/subtitle.srt"}
      ]
    }
  ],
  "video_file": "/waiter/file/{guid}/{hashed_path}",
  "subtitle_files": ["/path/to/subtitle.srt"],
  "next_link": "http://localhost:8000/mediaviewer/autoplaydownloadlink/{next_id}/",
  "previous_link": null,
  "tv_id": 404,
  "tv_name": "Slow Horses",
  "ismovie": false,
  "binge_mode": true
}
```

### 2. Movie Directory Listing - `/waiter/dir/<guid>/json`

Returns metadata for a movie directory.

**Example Request:**
```bash
curl http://localhost:5000/waiter/dir/{guid}/json
```

### 3. Autoplay Metadata - `/waiter/file/<guid>/autoplay/json`

Returns video player metadata for autoplay mode (TV episodes only).

**Example Request:**
```bash
curl http://localhost:5000/waiter/file/{guid}/autoplay/json
```

**Response:**
```json
{
  "title": "S04 E01: Identity Theft",
  "video_file": "/waiter/file/{guid}/{hashed_path}",
  "subtitle_files": ["/path/to/subtitle.srt"],
  "hashPath": "{hashed_path}",
  "next_link": "http://localhost:8000/mediaviewer/autoplaydownloadlink/{next_id}/",
  "previous_link": null,
  "CAST_ID": "{google_cast_app_id}"
}
```

### 4. Video Streaming Metadata - `/waiter/stream/<guid>/<hashPath>/json`

Returns video player metadata for direct streaming.

**Example Request:**
```bash
curl http://localhost:5000/waiter/stream/{guid}/{hashPath}/json
```

### 5. Watch Party Metadata - `/waiter/watch-party/<guid>/<hashPath>/json`

Returns video player metadata including Jitsi watch party integration.

**Example Request:**
```bash
curl http://localhost:5000/waiter/watch-party/{guid}/{hashPath}/json
```

**Response includes additional fields:**
```json
{
  "jitsi_jwt": "{encoded_jwt_token}",
  "watch_party_room_name": "{random_room_name}",
  "video_stream_url": "/waiter/file/{guid}/"
}
```

## Integration with MediaViewer

### Frontend Flow

1. **Get Stream URL** - Frontend requests episode stream from MediaViewer API:
   ```
   GET /api/v2/episodes/{episode_id}/stream/
   ```

2. **Receive GUID** - MediaViewer returns stream URL with download token GUID:
   ```json
   {
     "stream_url": "localhost:5000/waiter/file/{guid}/",
     "episode_id": 11255,
     "episode_name": "S04 E01: Identity Theft",
     "guid": "{guid}"
   }
   ```

3. **Fetch Metadata** - Frontend fetches JSON metadata:
   ```
   GET http://localhost:5000/waiter/file/{guid}/json
   ```

4. **Extract Video URL** - Frontend extracts `video_file` from JSON response for direct video playback

### React Hook Implementation

The `useEpisodeStream` hook in `frontend/src/hooks/useTV.ts` handles this flow automatically:

```typescript
const { streamUrl, metadata, isLoading, error } = useEpisodeStream(episodeId)

// streamUrl contains the direct video URL from metadata.video_file
// metadata contains all the JSON response data
```

## Running MediaWaiter

### Using Docker

```bash
docker run -d \
  --name mv-mediawaiter \
  -p 127.0.0.1:5000:5000 \
  -v /path/to/MediaWaiter:/code \
  -v /path/to/tv_shows:/www/media/tv \
  -v /path/to/movies:/www/media/movies \
  -e PYTHONPATH=/code/src \
  -e MW_BASE_PATH=/www/media \
  -e MW_MEDIA_DIRS=tv,movies \
  kyokley/mediawaiter
```

### Using devenv "up" script

```bash
cd /path/to/MediaWaiter
up
```

The `up` script automatically sets all required environment variables:
- `FLASK_DEBUG=1`
- `MW_USE_NGINX=false`
- `MW_BASE_PATH=/home/yokley`
- `MW_MEDIA_DIRS=tv_shows2,Movies`
- `MW_WAITER_USERNAME=waiter`
- `MW_WAITER_PASSWORD`
- `MW_MEDIAVIEWER_BASE_URL=http://127.0.0.1:8000/mediaviewer`

## Error Handling

All JSON endpoints return error responses in the same format:

```json
{
  "error": "Error message description"
}
```

**HTTP Status Codes:**
- `200 OK` - Success
- `400 Bad Request` - Invalid token, missing file, or other client error

## Authentication

All endpoints require a valid download token GUID obtained from MediaViewer's API. The GUID is validated against MediaViewer's `/api/downloadtoken/{guid}/` endpoint.

Token validation checks:
- Token exists
- Token is valid (`isvalid: true`)
- Token hasn't expired
- Requested file type matches token type (movie vs TV)

## Route Ordering

**Important**: The route ordering in `waiter.py` is critical. Specific routes must be defined before catch-all routes:

1. `/file/<guid>/json` - ✅ Defined first
2. `/file/<guid>/autoplay/json` - ✅ Defined before catch-all
3. `/file/<guid>/<path:hashPath>` - ✅ Defined last (catch-all)

This ensures JSON endpoints aren't captured by the file download handler.

## Testing

### Test Episode
- TV Show: Slow Horses (ID: 404)
- Episode: S04E01 - Identity Theft (ID: 11255)
- Path: `/home/yokley/tv_shows2/Slow.Horses`

### Test Flow

```bash
# 1. Get auth token
TOKEN=$(curl -s -X POST http://localhost:8000/mediaviewer/api/v2/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "testpass123"}' | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['data']['access'])")

# 2. Get stream URL
STREAM_DATA=$(curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/mediaviewer/api/v2/episodes/11255/stream/)

# 3. Extract GUID
GUID=$(echo "$STREAM_DATA" | python3 -c "import sys, json; print(json.load(sys.stdin)['guid'])")

# 4. Fetch JSON metadata
curl -s "http://localhost:5000/waiter/file/$GUID/json" | python3 -m json.tool
```

## Code Changes Summary

### Backend (`mediawaiter/waiter.py`)

1. **Refactored existing routes** to extract data logic into helper functions:
   - `_get_dirPath_data(guid)` - Movie directory data
   - `_get_file_data(guid)` - TV episode data
   - `_autoplay_data(guid)` - Autoplay data
   - `_video_data(guid, hashPath)` - Streaming data
   - `_watch_party_data(guid, hashPath)` - Watch party data

2. **Added JSON route handlers** that return helper function data as JSON:
   - `get_dirPath_json(guid)`
   - `get_file_json(guid)`
   - `autoplay_json(guid)`
   - `video_json(guid, hashPath)`
   - `watch_party_json(guid, hashPath)`

3. **Updated HTML route handlers** to use helper functions with `render_template(**data)`

4. **Fixed route ordering** to ensure JSON routes match before catch-all routes

### Frontend (`frontend/src/hooks/useTV.ts`)

1. **Added `MediaWaiterMetadata` interface** for type safety
2. **Updated `useEpisodeStream` hook** to:
   - Fetch stream URL from MediaViewer API
   - Append `/json` to get metadata
   - Extract `video_file` for direct playback
   - Return both `streamUrl` and `metadata`

### Frontend (`frontend/src/components/VideoPlayer.tsx`)

1. **Updated to use metadata** from `useEpisodeStream` hook
2. **Added subtitle track support** from `metadata.subtitle_files`

## Benefits

- **Programmatic Access**: Frontend can access video metadata without HTML parsing
- **Type Safety**: Structured JSON responses enable strong typing in TypeScript
- **Flexibility**: Same data can power multiple UI implementations
- **Subtitle Support**: Direct access to subtitle file paths
- **Navigation**: Access to next/previous episode links for binge watching
- **Reduced Coupling**: Frontend doesn't need to understand HTML structure
