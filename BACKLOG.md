# Backlog: Type Safety Improvements

This document tracks suppressed type errors that should be addressed incrementally. These errors were suppressed on **2025-12-29** to enable CI enforcement while allowing incremental fixes.

## Summary

| File | Errors | Priority |
|------|--------|----------|
| `amc_peripheral/radio/radio_cog.py` | 19 | High |
| `amc_peripheral/bot/knowledge_cog.py` | 7 | Medium |
| `amc_peripheral/bot/utils_cog.py` | 2 | Low |
| `amc_peripheral/bot/bot.py` | 2 | Low |
| `amc_peripheral/radio/radio.py` | 2 | Low |
| `amc_peripheral/radio/liquidsoap.py` | 1 | Low |
| `amc_peripheral/utils/discord_utils.py` | 1 | Low |
| `amc_peripheral/utils/game_utils.py` | 1 | Low |

**Total: 37 suppressed errors**

---

## High Priority: radio_cog.py

These errors are in critical functionality and should be fixed first.

### yt-dlp Type Issues

The `yt-dlp` library has incomplete type stubs. Consider:
1. Adding `# type: ignore` comments with explanations
2. Using `cast()` for known-correct types
3. Creating local type stubs if needed

**Locations:**
- Line 349: `YoutubeDL(ydl_info_opts)` - dict params not matching `_Params` type
- Line 351-352: `info_dict['entries']` - TypedDict missing `entries` key
- Line 396: `YoutubeDL(ydl_opts)` - dict params not matching type
- Line 397: `ydl.download([webpage_url])` - list type mismatch

### Nullable Type Handling

Variables extracted from yt-dlp info_dict can be `None` but are used without null checks:

**Locations:**
- Line 361: `title.lower()` - title can be None
- Line 366-367: `duration > 600` - duration can be None
- Line 371: `re.sub(..., title)` - title can be None

**Fix:** Add null checks before using these values:
```python
if title is None:
    raise Exception("Could not extract title from video")
if duration is None:
    raise Exception("Could not extract duration from video")
```

### discord.py Type Issues

**Locations:**
- Line 495: `member.roles` - User vs Member type confusion
- Line 701: `message.reference.resolved.attachments` - DeletedReferencedMessage doesn't have attachments
- Line 705: `attachment.save(local_path)` - string path vs PathLike

**Fix:** Add proper type narrowing:
```python
if isinstance(member, discord.Member):
    if any(r.id == DJ_ROLE_ID for r in member.roles):
        ...
```

### OpenAI SDK Type Issues

**Location:**
- Line 291: `chat.completions.create(...)` - messages type mismatch

**Fix:** Use proper `ChatCompletionMessageParam` types from the SDK.

---

## Medium Priority: knowledge_cog.py

These are in the knowledge/AI helper functionality.

**Errors:** 7 suppressed (mostly related to OpenAI SDK message types)

**Fix:** Import and use proper message param types:
```python
from openai.types.chat import ChatCompletionMessageParam
```

---

## Low Priority

### bot.py, radio.py (2 each)
Entry point initialization - likely settings/config type issues.

### liquidsoap.py (1)
Liquidsoap integration types.

### discord_utils.py (1)
- Line 7: `int(channel_id)` where channel_id can be None

**Fix:**
```python
if channel_id is None:
    return None
channel = bot.get_channel(int(channel_id))
```

### game_utils.py (1)
- Line 10: `urllib.parse.quote` type incompatibility

**Fix:** May need to cast or use a wrapper function.

---

## How to Fix Suppressed Errors

1. Search for `# pyrefly: ignore` comments in the codebase
2. Address the underlying issue
3. Remove the suppression comment
4. Run `uv run pyrefly check .` to verify the fix

## Commands

```bash
# Find all suppressed errors
grep -rn "pyrefly: ignore" amc_peripheral/

# Check current status
uv run pyrefly check .
```
