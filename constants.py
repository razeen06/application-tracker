GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

# Requested only by /connect-gmail -- separate from the login flow's
# "openid email profile" scope, which stays unaffected since this is passed
# as a per-call override to the same registered "google" Authlib client
# rather than a second client registration.
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
