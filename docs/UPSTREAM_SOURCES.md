# Upstream sources

## hongguo-drama

| Field | Recorded value |
| --- | --- |
| Repository URL | https://github.com/jackotom/hongguo-drama.git |
| Version / tag | `v7.5` |
| Commit SHA | `4ffff289d6dd289e589a0fd0e65aa7aa5c2a7567` |
| License | GNU General Public License version 3; upstream declares `GPL-3.0` in `package.json` |
| License evidence | `../hongguo-drama/LICENSE`, `../hongguo-drama/package.json`, and `../hongguo-drama/NOTICE` |
| Local checkout | `../hongguo-drama` (sibling of this repository) |
| Clone mode | Shallow, depth 1, single branch/tag, detached HEAD at `v7.5` |

Clone command, run from the parent directory:

```sh
git clone --depth 1 --branch v7.5 --single-branch https://github.com/jackotom/hongguo-drama.git hongguo-drama
```

The upstream checkout is retained unchanged as a reference. No upstream code
has been copied into DramaFlow. Upstream also includes component-specific
licensing information in `THIRD-PARTY-NOTICES.md` and component license files;
those remain in the reference checkout.
