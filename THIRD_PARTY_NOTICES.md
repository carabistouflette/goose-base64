# Third-party notices

The library source is licensed under Apache-2.0; see [LICENSE](LICENSE).
No third-party source is vendored in this repository.

The Goose compiler and standard library are external build and runtime
dependencies, not bundled source. Setup fetches the exact commit in
[GOOSE_REVISION](GOOSE_REVISION) from https://github.com/aardappel/goose. Their
own license applies to them; see the
[pinned upstream license](https://github.com/aardappel/goose/blob/eadca409f68210893f366e60d0c2f0dc29a339be/LICENSE).

`encode` delegates whole 3-byte groups to the pinned standard library's
`base64::encode` (`stdlib/base64.goose`). The final 1-2 byte group, the URL
alphabet mapping and the whole decoder are implemented here. The alphabet
arithmetic follows RFC 4648 tables 1 and 2, which are a specification rather
than licensed source.

The test oracle uses Python's `base64` module as an independent implementation
and adds its own canonicality check. Python is an external development tool
governed by its own license.

CMake, Make, GCC, Clang, ASan, UBSan and GitHub Actions are external development
tools governed by their own licenses. GitHub Actions are pinned to immutable
commits in CI; they are not part of the distributed library.
