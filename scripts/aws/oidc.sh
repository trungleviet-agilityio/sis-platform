# shellcheck shell=bash
# Credit: adapted from ship-it-safely scripts/lib.sh (oidc_token, jwt_claim; lab ADR 0007 S31).
# OIDC helpers for scripts/aws/*.sh. Source it after scripts/lib.sh (mask, redact_ids); do not run it.
# Bash 3.2 compatible.

# oidc_token: print the job's GitHub OIDC token for the STS audience (needs id-token: write) and mask it.
oidc_token() {
  local response token
  require_cmd jq "install jq"
  require_cmd curl "install curl"
  if [ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ] || [ -z "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]; then
    die "no OIDC token request variables (the job needs id-token: write)"
  fi
  response="$(curl -fsS -H "Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" \
    "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=sts.amazonaws.com")" ||
    die "OIDC token request failed"
  token="$(printf '%s' "$response" | jq -r '.value // empty')"
  [ -n "$token" ] || die "OIDC token response has no value"
  mask "$token" >&2
  printf '%s' "$token"
}

# jwt_claim <token> <claim>: print one claim of the JWT payload (empty when absent). Never prints the token.
jwt_claim() {
  local payload
  payload="$(printf '%s' "$1" | cut -d. -f2 | tr '_-' '/+')"
  while [ $((${#payload} % 4)) -ne 0 ]; do payload="${payload}="; done
  printf '%s' "$payload" | base64 -d 2>/dev/null | jq -r --arg claim "$2" '.[$claim] // empty | tostring'
}
