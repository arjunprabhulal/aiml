# Parallel builds

`docuctl build --jobs 4` renders four pages at a time. Pages that include other pages
are rendered after the pages they include, so the output does not depend on the job count.
