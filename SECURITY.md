# Security

This is an experimental Base64 library with no stable release yet. Only the
latest published commit is maintained.

The library is strict by design: it rejects whitespace, the other alphabet's two
extra characters, misplaced padding and non-canonical trailing bits, and it
never mutates the caller's buffer on failure. Applications must still bound
input reads, output growth and total work, and must handle every non-`None`
error before using the output.

Two properties matter for security-sensitive use:

- **Canonicality.** Accepting non-canonical text makes the encoding
  non-injective: two distinct strings decode to the same bytes. A key
  identifier, a detached signature or any value compared as text in one place
  and as bytes in another can then disagree. This library rejects such text as
  `NonCanonical`; a permissive decoder does not.
- **Not constant-time.** Decoding is not constant-time and must not be used to
  compare secrets. Compare decoded bytes with a dedicated constant-time routine.

Base64 is an encoding, not encryption or authentication. It provides no
confidentiality and no integrity.

Please report suspected vulnerabilities privately using GitHub's **Report a
vulnerability** option in this repository's Security tab when available. If that
option is unavailable, contact the repository owner privately through their
GitHub profile before sharing sensitive details. Do not include credentials or
private data in a report, and avoid public exploit details before a fix exists.
Include the full source and compiler revisions, platform, minimal reproducer and
expected versus actual behavior. No response-time guarantee is offered.
