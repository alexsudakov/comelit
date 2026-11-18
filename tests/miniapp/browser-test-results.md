# Browser test execution

Dependency preparation is limited to `npm ci`. Run the browser suites with:

`PLAYWRIGHT_BROWSERS_PATH=<absolute> npm run test:browser`

`npm ci` does not change `package-lock.json` and does not download browsers when `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` is set.

`NOT_RUN_IN_DEV_SANDBOX`: Native VERIFY image `hermes-dev-v2-verify@sha256:27dfc103472981531d590a4e830acf804d4cd7afbba7d14b05f4c35ac783c242` does not contain Playwright/Chromium, and the v1 contract cannot select a project-specific image (`DEV_V2_VERIFY_IMAGE` is a global worker environment variable).

The GitHub `test` job continues to run both `viewer.browser.cjs` and `webcodecs.browser.cjs`; it is not disabled.
