"""Child-only POSIX file-size limit; exec without preexec_fn in threaded callers."""

import os
import resource
import sys


if __name__ == '__main__':
    limit = int(sys.argv[1])
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    os.execvp(sys.argv[2], sys.argv[2:])
