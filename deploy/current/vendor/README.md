# Observed Mac SoX artifact

`macos-arm64/sox` is the exact executable used by the current Mac worker.
Its size and SHA-256 are pinned in `../artifacts.lock.json`. It is retained
because the original installation did not record a source revision or build
command. The executable reports `SoX v` with an empty version field; **14.4.2
is not a verified version of this binary**.

`sox-14.4.2-source.tar.gz` is the upstream reference source downloaded from
https://sourceforge.net/projects/sox/files/sox/14.4.2/sox-14.4.2.tar.gz/download .
`SOX-COPYING`, `SOX-LICENSE.GPL`, and `SOX-LICENSE.LGPL` come from that archive.
This reference source does not prove a matching rebuild of the installed binary.
Before distributing this binary outside the private installation, establish its
corresponding source/build provenance or replace it with a reproducible build.
The current snapshot guarantees restoration of the observed executable bytes,
not a reproducible compilation of SoX.
