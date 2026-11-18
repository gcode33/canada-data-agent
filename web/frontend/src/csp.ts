// The page's Content Security Policy (A8 §10/§11). One definition: vite.config.ts injects it
// into the built page, and the e2e suite asserts the built page carries exactly this.
// `frame-ancestors` is absent because browsers ignore it in a <meta> tag.
export const CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self'",
  "connect-src 'self'",
  "base-uri 'none'",
  "form-action 'self'",
  "require-trusted-types-for 'script'",
  "trusted-types 'none'",
].join("; ");
