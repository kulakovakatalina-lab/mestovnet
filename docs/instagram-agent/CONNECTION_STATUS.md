# Instagram connection status

Checked: 2026-10-15, 21:06 Europe/Moscow.
Account: @mestovnet82. API account type: MEDIA_CREATOR.
Instagram user_id: 17841424425560234.

## Verified with the repository secret

- Basic account request succeeds, and the username matches mestovnet82.
- GET /{user_id}/content_publishing_limit succeeds. The quota endpoint is accessible; this does not prove permission to create or publish media.
- GET /{user_id}/insights?metric=reach&period=day succeeds with one result series. Other metrics and media insights have not been checked.
- No content, media containers or messages were created. The access token is read from INSTAGRAM_ACCESS_TOKEN and is not printed.

Run: https://github.com/kulakovakatalina-lab/mestovnet/actions/runs/38782839152
Workflow: .github/workflows/instagram-connection-check.yml

## Not yet verified

- The permissions-list probe returned HTTP 400 / Meta code 100. No conclusion about granted/missing scopes is drawn from that error. Raw error messages are deliberately not logged.
- Actual content publishing, including Stories, requires a separate check of supported account type, scopes and formats. No publishing test has been authorized yet.
- Token expiration is unknown: the secret contains a token value without issued_at/expires_in metadata. A successful account request does not establish that it is long-lived.

## Token lifecycle setup

Obtain the expiry from the original token issuance response or the Meta interface, if shown. For an API exchange from short-lived to long-lived credentials, the Instagram app secret is required. If that route is used, save the Instagram app secret in GitHub Actions Secrets as INSTAGRAM_APP_SECRET, never in repository files or chat. Exchange/refresh code must keep the returned token private and persist expiry metadata. Automatic secret replacement requires a supported credential-store write mechanism; the current diagnostic workflow has no such permissions. No exchange or refresh has been attempted.

## Next steps

1. Confirm the token's expiry and arrange renewal before unattended operation.
2. Check instagram_business_content_publish in the Meta application's permissions/settings and grant it through authorization if needed.
3. Prepare a reviewable sample image/caption and only publish after explicit approval.
4. Test other required metrics, media formats and Stories separately. Reach access alone does not confirm all analytics functionality.
