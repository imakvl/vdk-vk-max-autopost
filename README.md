# VDK VK → MAX autopost

Transfers new posts with text and up to 12 photos from vk.com/myvdk to max.ru/myvdk.

1. Create a PUBLIC GitHub repo, upload all files (including `.github/workflows/autopost.yml`).
2. Settings → Secrets and variables → Actions: add `VK_TOKEN`, `MAX_TOKEN`, `MAX_CHAT_ID` (`-69049058558184`). Rotate any previously shared tokens first.
3. Settings → Actions → General → Workflow permissions: choose **Read and write permissions** if needed.
4. Actions → VK to MAX autopost → Run workflow. First run initializes `state.json` without reposting old content.
5. Publish a new VK post and run workflow again. Check MAX and Actions logs.
6. Schedule checks every 10 minutes (GitHub may delay scheduled workflows).

Caveats: no video/reposts/stories; only up to 12 photos; captions may exceed MAX text limit; photos that fail to upload halt the run; transient uncertainty after MAX accepted a post but before state is committed can still produce a duplicate on retry. High-volume walls require pagination. This is an initial working implementation, not exactly-once delivery.
