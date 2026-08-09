# How to sign

Signing means you agree with the claim in section I of [the declaration](https://agiasap.org/).
It does not commit you to anything else: not to a lane, not to money, not to any position taken
in section III or IV.

## The easy way, about thirty seconds

[**Open the signing form**](https://github.com/pjdurden/agiasap/issues/new?template=sign.yml).

Fill in three fields and submit. A workflow opens the pull request for you and comments on your
issue to say it did. No git, no fork, no JSON.

Your GitHub username is taken from the issue author, never from anything you type. That is what
makes signing as somebody else impossible rather than merely discouraged.

## The manual way

1. Fork this repository.
2. Add `data/signatures/<your-handle>.json`. The filename must be your GitHub handle, lowercase.

```json
{
  "name": "Ada Lovelace",
  "github": "adalovelace",
  "lane": "infra",
  "signed": "2026-08-09"
}
```

3. Open a pull request titled `sign: @yourhandle`.

Optional fields: `url` (must be `https://`) and `affiliation` (60 characters max).
`lane` is one of `infra`, `research`, `compute`, `evals`, `signal`, `capital`.

One file per person, which means two people signing at the same time can never conflict.

## What CI enforces

- **You may only add yourself.** A newly added signature file must be named for the account that
  opened the pull request.
- **The filename must match the `github` field inside it.** Duplicates become impossible, since a
  directory cannot hold two files of the same name.
- One signature per pull request. No future dates, no unknown fields, no malformed handles.
- Existing signatures cannot be edited in place, only removed and re-added.

## About the affiliation field

Put your employer there only if you are comfortable with it reading as your employer's position
to someone skimming. It will. If in doubt, leave it blank or write "independent". We will never
add an affiliation on your behalf, and we will remove one on request without asking why.

## Removing yourself

Delete your file in a pull request, or say so in any issue, or write to the address in the
colophon. **Removals are accepted from anyone, are never questioned, and do not require the
account that signed.** If you want off this list you get off this list, including if someone
else put you on it.

## The recognition board is not a signature list

The table in section VI is compiled from public GitHub contribution data. Being on it is not
signing, is not endorsement, and several people on it would disagree with most of the document.
To be excluded, add your handle to `optout.txt` or write to the same address.
