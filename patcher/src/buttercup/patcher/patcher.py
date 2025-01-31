from dataclasses import dataclass, field
from pathlib import Path
from buttercup.common.datastructures.msg_pb2 import ConfirmedVulnerability, Patch
from redis import Redis
from buttercup.common.queues import ReliableQueue, QueueFactory, RQItem, QueueNames, GroupNames
from buttercup.common.logger import setup_logging
import time

logger = setup_logging(__name__)

MOCK_LIBPNG_PATCH = """diff --git a/pngrutil.c b/pngrutil.c
index 01e08bfe7..7c609b4b4 100644
--- a/pngrutil.c
+++ b/pngrutil.c
@@ -1419,13 +1419,12 @@ png_handle_iCCP(png_structrp png_ptr, png_inforp info_ptr, png_uint_32 length)
    if ((png_ptr->colorspace.flags & PNG_COLORSPACE_HAVE_INTENT) == 0)
    {
       uInt read_length, keyword_length;
-      uInt max_keyword_wbytes = 41;
-      wpng_byte keyword[max_keyword_wbytes];
+      char keyword[81];
 
       /* Find the keyword; the keyword plus separator and compression method
-       * bytes can be at most 41 wide characters long.
+       * bytes can be at most 81 characters long.
        */
-      read_length = sizeof(keyword); /* maximum */
+      read_length = 81; /* maximum */
       if (read_length > length)
          read_length = (uInt)length;
 
@@ -1443,12 +1442,12 @@ png_handle_iCCP(png_structrp png_ptr, png_inforp info_ptr, png_uint_32 length)
       }
 
       keyword_length = 0;
-      while (keyword_length < (read_length-1) && keyword_length < read_length &&
+      while (keyword_length < 80 && keyword_length < read_length &&
          keyword[keyword_length] != 0)
          ++keyword_length;
 
       /* TODO: make the keyword checking common */
-      if (keyword_length >= 1 && keyword_length <= (read_length-2))
+      if (keyword_length >= 1 && keyword_length <= 79)
       {
          /* We only understand '0' compression - deflate - so if we get a
           * different value we can't safely decode the chunk.
@@ -1477,13 +1476,13 @@ png_handle_iCCP(png_structrp png_ptr, png_inforp info_ptr, png_uint_32 length)
                   png_uint_32 profile_length = png_get_uint_32(profile_header);
 
                   if (png_icc_check_length(png_ptr, &png_ptr->colorspace,
-                      (char*)keyword, profile_length) != 0)
+                      keyword, profile_length) != 0)
                   {
                      /* The length is apparently ok, so we can check the 132
                       * byte header.
                       */
                      if (png_icc_check_header(png_ptr, &png_ptr->colorspace,
-                         (char*)keyword, profile_length, profile_header,
+                         keyword, profile_length, profile_header,
                          png_ptr->color_type) != 0)
                      {
                         /* Now read the tag table; a variable size buffer is
@@ -1513,7 +1512,7 @@ png_handle_iCCP(png_structrp png_ptr, png_inforp info_ptr, png_uint_32 length)
                            if (size == 0)
                            {
                               if (png_icc_check_tag_table(png_ptr,
-                                  &png_ptr->colorspace, (char*)keyword, profile_length,
+                                  &png_ptr->colorspace, keyword, profile_length,
                                   profile) != 0)
                               {
                                  /* The profile has been validated for basic

"""


@dataclass
class Patcher:
    task_storage_dir: Path
    redis: Redis | None = None
    sleep_time: float = 1
    mock_mode: bool = False

    vulnerability_queue: ReliableQueue | None = field(init=False, default=None)
    patches_queue: ReliableQueue | None = field(init=False, default=None)

    def __post_init__(self):
        if self.redis is not None:
            queue_factory = QueueFactory(self.redis)
            self.vulnerability_queue = queue_factory.create(QueueNames.CONFIRMED_VULNERABILITIES, GroupNames.CONFIRMED_VULNERABILITIES)
            self.patches_queue = queue_factory.create(QueueNames.PATCHES)

    def process_mocked_vulnerability(self, vuln: ConfirmedVulnerability) -> Patch | None:
        logger.info(f"Processing mocked vulnerability {vuln.crash.target.package_name}/{vuln.vuln_id}")
        if vuln.crash.target.package_name == "libpng":
            return Patch(
                task_id=vuln.crash.target.task_id,
                vulnerability_id=vuln.vuln_id,
                patch=MOCK_LIBPNG_PATCH,
            )

        return None

    def process_vulnerability(self, vuln: ConfirmedVulnerability) -> Patch | None:
        logger.info(f"Processing vulnerability {vuln.crash.target.package_name}/{vuln.vuln_id}")
        logger.debug(f"Vulnerability: {vuln}")
        res = None
        if self.mock_mode:
            res = self.process_mocked_vulnerability(vuln)

        if res is not None:
            logger.info(f"Processed vulnerability {vuln.crash.target.package_name}/{vuln.vuln_id}")
        else:
            logger.error(f"Failed to process vulnerability {vuln.crash.target.package_name}/{vuln.vuln_id}")

        return res

    def serve(self):
        """Main loop to process vulnerabilities from queue"""
        if self.redis is None:
            raise ValueError("Redis is not initialized, setup redis connection")

        logger.info("Starting patcher service")
        while True:
            rq_item: RQItem[ConfirmedVulnerability] | None = self.vulnerability_queue.pop()

            if rq_item is not None:
                vuln: ConfirmedVulnerability = rq_item.deserialized
                try:
                    patch = self.process_vulnerability(vuln)
                    if patch is not None:
                        self.patches_queue.push(patch)
                        self.vulnerability_queue.ack_item(rq_item.item_id)
                        logger.info(
                            f"Successfully generated patch for vulnerability {vuln.crash.target.package_name}/{vuln.vuln_id}"
                        )
                    else:
                        logger.error(
                            f"Failed to generate patch for vulnerability {vuln.crash.target.package_name}/{vuln.vuln_id}"
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to generate patch for vulnerability {vuln.crash.target.package_name}/{vuln.vuln_id}: {e}"
                    )

            logger.info(f"Sleeping for {self.sleep_time} seconds")
            time.sleep(self.sleep_time)
