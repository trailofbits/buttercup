MOCK_LIBPNG_FUNCTION_CODE = """
void /* PRIVATE */
png_handle_iCCP(png_structrp png_ptr, png_inforp info_ptr, png_uint_32 length)
/* Note: this does not properly handle profiles that are > 64K under DOS */
{
   png_const_charp errmsg = NULL; /* error message output, or no error */
   int finished = 0; /* crc checked */

   png_debug(1, "in png_handle_iCCP");

   if ((png_ptr->mode & PNG_HAVE_IHDR) == 0)
      png_chunk_error(png_ptr, "missing IHDR");

   else if ((png_ptr->mode & (PNG_HAVE_IDAT|PNG_HAVE_PLTE)) != 0)
   {
      png_crc_finish(png_ptr, length);
      png_chunk_benign_error(png_ptr, "out of place");
      return;
   }

   /* Consistent with all the above colorspace handling an obviously *invalid*
    * chunk is just ignored, so does not invalidate the color space.  An
    * alternative is to set the 'invalid' flags at the start of this routine
    * and only clear them in they were not set before and all the tests pass.
    */

   /* The keyword must be at least one character and there is a
    * terminator (0) byte and the compression method byte, and the
    * 'zlib' datastream is at least 11 bytes.
    */
   if (length < 14)
   {
      png_crc_finish(png_ptr, length);
      png_chunk_benign_error(png_ptr, "too short");
      return;
   }

   /* If a colorspace error has already been output skip this chunk */
   if ((png_ptr->colorspace.flags & PNG_COLORSPACE_INVALID) != 0)
   {
      png_crc_finish(png_ptr, length);
      return;
   }

   /* Only one sRGB or iCCP chunk is allowed, use the HAVE_INTENT flag to detect
    * this.
    */
   if ((png_ptr->colorspace.flags & PNG_COLORSPACE_HAVE_INTENT) == 0)
   {
      uInt read_length, keyword_length;
      uInt max_keyword_wbytes = 41;
      wpng_byte keyword[max_keyword_wbytes];

      /* Find the keyword; the keyword plus separator and compression method
       * bytes can be at most 41 wide characters long.
       */
      read_length = sizeof(keyword); /* maximum */
      if (read_length > length)
         read_length = (uInt)length;

      png_crc_read(png_ptr, (png_bytep)keyword, read_length);
      length -= read_length;

      /* The minimum 'zlib' stream is assumed to be just the 2 byte header,
       * 5 bytes minimum 'deflate' stream, and the 4 byte checksum.
       */
      if (length < 11)
      {
         png_crc_finish(png_ptr, length);
         png_chunk_benign_error(png_ptr, "too short");
         return;
      }

      keyword_length = 0;
      while (keyword_length < (read_length-1) && keyword_length < read_length &&
         keyword[keyword_length] != 0)
         ++keyword_length;

      /* TODO: make the keyword checking common */
      if (keyword_length >= 1 && keyword_length <= (read_length-2))
      {
         /* We only understand '0' compression - deflate - so if we get a
          * different value we can't safely decode the chunk.
          */
         if (keyword_length+1 < read_length &&
            keyword[keyword_length+1] == PNG_COMPRESSION_TYPE_BASE)
         {
            read_length -= keyword_length+2;

            if (png_inflate_claim(png_ptr, png_iCCP) == Z_OK)
            {
               Byte profile_header[132]={0};
               Byte local_buffer[PNG_INFLATE_BUF_SIZE];
               png_alloc_size_t size = (sizeof profile_header);

               png_ptr->zstream.next_in = (Bytef*)keyword + (keyword_length+2);
               png_ptr->zstream.avail_in = read_length;
               (void)png_inflate_read(png_ptr, local_buffer,
                   (sizeof local_buffer), &length, profile_header, &size,
                   0/*finish: don't, because the output is too small*/);

               if (size == 0)
               {
                  /* We have the ICC profile header; do the basic header checks.
                   */
                  png_uint_32 profile_length = png_get_uint_32(profile_header);

                  if (png_icc_check_length(png_ptr, &png_ptr->colorspace,
                      (char*)keyword, profile_length) != 0)
                  {
                     /* The length is apparently ok, so we can check the 132
                      * byte header.
                      */
                     if (png_icc_check_header(png_ptr, &png_ptr->colorspace,
                         (char*)keyword, profile_length, profile_header,
                         png_ptr->color_type) != 0)
                     {
                        /* Now read the tag table; a variable size buffer is
                         * needed at this point, allocate one for the whole
                         * profile.  The header check has already validated
                         * that none of this stuff will overflow.
                         */
                        png_uint_32 tag_count =
                           png_get_uint_32(profile_header + 128);
                        png_bytep profile = png_read_buffer(png_ptr,
                            profile_length, 2/*silent*/);

                        if (profile != NULL)
                        {
                           memcpy(profile, profile_header,
                               (sizeof profile_header));

                           size = 12 * tag_count;

                           (void)png_inflate_read(png_ptr, local_buffer,
                               (sizeof local_buffer), &length,
                               profile + (sizeof profile_header), &size, 0);

                           /* Still expect a buffer error because we expect
                            * there to be some tag data!
                            */
                           if (size == 0)
                           {
                              if (png_icc_check_tag_table(png_ptr,
                                  &png_ptr->colorspace, (char*)keyword, profile_length,
                                  profile) != 0)
                              {
                                 /* The profile has been validated for basic
                                  * security issues, so read the whole thing in.
                                  */
                                 size = profile_length - (sizeof profile_header)
                                     - 12 * tag_count;

                                 (void)png_inflate_read(png_ptr, local_buffer,
                                     (sizeof local_buffer), &length,
                                     profile + (sizeof profile_header) +
                                     12 * tag_count, &size, 1/*finish*/);

                                 if (length > 0 && !(png_ptr->flags &
                                     PNG_FLAG_BENIGN_ERRORS_WARN))
                                    errmsg = "extra compressed data";

                                 /* But otherwise allow extra data: */
                                 else if (size == 0)
                                 {
                                    if (length > 0)
                                    {
                                       /* This can be handled completely, so
                                        * keep going.
                                        */
                                       png_chunk_warning(png_ptr,
                                           "extra compressed data");
                                    }

                                    png_crc_finish(png_ptr, length);
                                    finished = 1;

# if defined(PNG_sRGB_SUPPORTED) && PNG_sRGB_PROFILE_CHECKS >= 0
                                    /* Check for a match against sRGB */
                                    png_icc_set_sRGB(png_ptr,
                                        &png_ptr->colorspace, profile,
                                        png_ptr->zstream.adler);
# endif

                                    /* Steal the profile for info_ptr. */
                                    if (info_ptr != NULL)
                                    {
                                       png_free_data(png_ptr, info_ptr,
                                           PNG_FREE_ICCP, 0);

                                       info_ptr->iccp_name = png_voidcast(char*,
                                           png_malloc_base(png_ptr,
                                           keyword_length+1));
                                       if (info_ptr->iccp_name != NULL)
                                       {
                                          memcpy(info_ptr->iccp_name, keyword,
                                              keyword_length+1);
                                          info_ptr->iccp_proflen =
                                              profile_length;
                                          info_ptr->iccp_profile = profile;
                                          png_ptr->read_buffer = NULL; /*steal*/
                                          info_ptr->free_me |= PNG_FREE_ICCP;
                                          info_ptr->valid |= PNG_INFO_iCCP;
                                       }

                                       else
                                       {
                                          png_ptr->colorspace.flags |=
                                             PNG_COLORSPACE_INVALID;
                                          errmsg = "out of memory";
                                       }
                                    }

                                    /* else the profile remains in the read
                                     * buffer which gets reused for subsequent
                                     * chunks.
                                     */

                                    if (info_ptr != NULL)
                                       png_colorspace_sync(png_ptr, info_ptr);

                                    if (errmsg == NULL)
                                    {
                                       png_ptr->zowner = 0;
                                       return;
                                    }
                                 }
                                 if (errmsg == NULL)
                                    errmsg = png_ptr->zstream.msg;
                              }
                              /* else png_icc_check_tag_table output an error */
                           }
                           else /* profile truncated */
                              errmsg = png_ptr->zstream.msg;
                        }

                        else
                           errmsg = "out of memory";
                     }

                     /* else png_icc_check_header output an error */
                  }

                  /* else png_icc_check_length output an error */
               }

               else /* profile truncated */
                  errmsg = png_ptr->zstream.msg;

               /* Release the stream */
               png_ptr->zowner = 0;
            }

            else /* png_inflate_claim failed */
               errmsg = png_ptr->zstream.msg;
         }

         else
            errmsg = "bad compression method"; /* or missing */
      }

      else
         errmsg = "bad keyword";
   }

   else
      errmsg = "too many profiles";

   /* Failure: the reason is in 'errmsg' */
   if (finished == 0)
      png_crc_finish(png_ptr, length);

   png_ptr->colorspace.flags |= PNG_COLORSPACE_INVALID;
   png_colorspace_sync(png_ptr, info_ptr);
   if (errmsg != NULL) /* else already output */
      png_chunk_benign_error(png_ptr, errmsg);
}
"""
