#!/usr/bin/python2
#
# Example application for managing an iPod and its tracks.
# Main feature revolves around synchronisation between a larger
# local database assisted by smart playlists
#
# Licenced under the Gnu General Public Licence, version 2
#
# Copyright 2006 Ben Buxton <bb at cactii dot(.) net>

import os, os.path
import gpod
import statvfs
import tempfile
import re
import sys
from optparse import OptionParser
import eyed3
import eyed3.mp3
import eyed3.id3
import imghdr
import shutil
import time
import stat
import hashlib
import struct

mountpoint = "/mnt/ipod" # Ipod mount point
dotitdb = os.path.join(os.environ['HOME'],".gtkpod")

class Spinner: # Our little progress spinner
    def __init__(self):
        self.char = ['|', '/', '-', '\\', '-']
        self.len  = len(self.char)
        self.curr = 0

    def Print(self):
        self.curr = (self.curr + 1) % self.len
        str = self.char[self.curr]
        sys.stdout.write("\r%s" % str)
        sys.stdout.flush()

    def Done(self):
        sys.stdout.write("\r")


# Given files and/or dirs, returns list of all valid files
def validFiles(files):
  fls = []
  Msg("DEBUG: Walking %s" % files, 2)
  for file in files:
    if not os.path.isfile(file) and not os.path.isdir(file):
      Msg(1, "WARN: Can't find file %s" % file)
      continue
    if os.path.isdir(file):
      for root,dirs,f in os.walk(os.path.abspath(file)):
        for name in f:
          fls.append(os.path.join(root,name))
    else:
      fls.append(file)
  return fls

# Given an mp3 file, extracts thumbnail and returns the filename
# Filename is basically <file_mdsum>.jpg
def thumbfile(file):
  global tmpDir
  global dryRun
  if dryRun or not eyed3.mp3.isMp3File(file):
    return None
  try:
    audioFile = eyed3.mp3.Mp3AudioFile(file, eyed3.id3.ID3_ANY_VERSION)
  except:
    return None
  tag = audioFile.tag
  images = tag.images
  if not tmpDir:
    tmpDir = tempfile.mkdtemp()
  for img in images:
    try:
      imgFile = img.getDefaultFileName(str(1))
      img.writeFile(tmpDir, imgFile)
      imgFile = os.path.join(tmpDir, imgFile)
    except:
      continue
    f = open(os.path.join(imgFile), "rb")
    m = hashlib.md5()
    while True:
      d = f.read(8096)
      if not d: break
      m.update(d)
    f.close()
    fnam = m.hexdigest() + ".jpg"
    f2 = os.path.join(tmpDir, fnam)
    if imghdr.what(imgFile) == "jpeg" and not os.path.isfile(f2):
      os.rename (imgFile, f2)
    else:
      Msg("DEBUG: %s doesn't appear to be a jpeg file, ignoring" % imgFile, 2)
      os.unlink(imgFile)
    return f2

# Returns bytes free space on filesystem at (dir)
def diskFree(dir):
  fs_stat = os.statvfs(dir)
  return fs_stat[statvfs.F_BSIZE] * fs_stat[statvfs.F_BFREE]

# Returns total disk space on filesystem at (dir)
def diskSpace(dir):
  fs_stat = os.statvfs(dir)
  return fs_stat[statvfs.F_BSIZE] * fs_stat[statvfs.F_BLOCKS]

# Get size of file on disk
def fileSize(file):
  try:
    file_stat = os.stat(file)
  except:
    return 0
  return file_stat[stat.ST_SIZE] # Get filesize

# Print messages, if we are verbose enough
def Msg(msg, level):
  global verbose
  if verbose >= level:
    print msg

# Return track rating as string eg '***'
def stars(t):
  if not t.rating:
    return '.'
  rate = ''
  for i in range(t.rating/20):
    rate += '*'
  return rate

# Dumps some information about a track
def showFile(t):
  if t.time_added == 0:
    date = "Never"
  else:
    #date = time.strftime("%d %b", time.gmtime(t.time_added-2082844800)) #broken
    date = "Never"
  remarks = ""
  print " %-23.23s     %-17.17s   %-20.20s  %-5s     %-8s     %-3d    %-4d  %-3d" % (t.title , t.artist, t.album, stars(t), date, t.playcount, t.id, t.bitrate)

# Present options to user, return if yes
def askIfOk(msg):
  sys.stdout.write(msg)
  sys.stdout.flush()
  answer = sys.stdin.readline().strip()
  if answer == "y" or answer == "Y":
    return
  print "Aborting..."
  sys.exit(0)

# Read ipod -> local track map file
# Fills ipodMap[] where key = ipod id, value = local id
# Terrible code, needs a bit cleanup
def readMap():
  global ipodMap
  global ipodMapNew
  global l_itdb
  global i_itdb
  ipodMapNew = {}
  ipodMap[0] = 0
  iMap = {}
  lMap = {}
  podMap = {}
  locMap = {}
  lfmap = {}
  ifmap = {}
  mapFile = os.path.join(dotitdb, "map")
  Msg("DEBUG: Reading ipod map file", 2)
  try:
    mf = file(mapFile, "r")
  except:
    Msg("DEBUG: No map file, will create later", 2)
    return None
  for line in mf.readlines():
    line = line.strip()
    (localFile,ipodFile) = line.split(";")
    if not localFile or not ipodFile:
      continue
    iMap[ipodFile] = localFile
    lMap[localFile] = ipodFile
    lfmap[line] = localFile
    ifmap[line] = ipodFile
  mf.close()
  for track in gpod.sw_get_tracks(i_itdb):
    path = str(track.ipod_path)
    if iMap.has_key(path):
      podMap[path] = track.id
  for track in gpod.sw_get_tracks(l_itdb):
    path = str(track.ipod_path)
    if lMap.has_key(path):
      locMap[path] = track.id
  for f in lfmap.keys():
    lf = lfmap[f]
    i_f = ifmap[f]
    if not podMap.has_key(i_f) or not locMap.has_key(lf):
      continue
    podid = int(podMap[ifmap[f]])
    locid = int(locMap[lfmap[f]])
    ipodMap[podid] = locid
  for t in gpod.sw_get_tracks(i_itdb):
    if not ipodMap.has_key(t.id):
      ipodMap[t.id] = 0

# Sets ipod map. Takes local track and ipod track as arg
def setMap(ltrack, itrack):
  global ipodMapNew
  lfile = ltrack.ipod_path
  ifile = itrack.ipod_path
  if lfile and ifile:
    ipodMapNew[lfile] = ifile

# Deletes ipod track 'id' from map
def delMap(track):
  global ipodMapNew
  for t in ipodMapNew.keys():
    if ipodMapNew[t] == str(track.ipod_path):
      del ipodMapNew[t]
      return

# Write new ipodmap to file
def writeMap():
  global ipodMapNew
  global dryRun
  if dryRun:
    Msg("DEBUG: Not writing ipod map file (dry-run)", 2)
    return
  Msg("DEBUG: Writing ipod map file", 2)
  mapFile = os.path.join(dotitdb, "map")
  mf = file(mapFile, "w")
  for l in ipodMapNew.keys():
    mf.write("%s;%s\n" % (str(l),str(ipodMapNew[l])))
  mf.close()

# Hash of a file, as used by gtkpod extended info file
# Combination of size and first 16k of file for speed
def fileHash(filename):
  if not os.path.isfile(filename):
    return ""
  sha1 = hashlib.sha1()
  size = os.path.getsize(filename)
  sha1.update(struct.pack("<L", size))
  sha1.update(open(filename).read(16384))
  return sha1.hexdigest()

# Write the gtkpod extended info file
def writeExt(forceHash):
  global l_itdb
  global dryRun
  global extInfo
  extFile = options.dbname + ".ext"
  s = Spinner()
  sum = fileHash(options.dbname)
  if not dryRun:
    ef = file(extFile, "w")
    ef.write("itunesdb_hash=%s\n" % sum)
    ef.write("version=0.99.1\n")
  count = 0
  for track in gpod.sw_get_tracks(l_itdb):
    id = track.id
    s.Print()
    if not dryRun:
      ef.write("id=%d\n" % id)
      if not extInfo.has_key(id):
        extInfo[id] = {}
        extInfo[id]['filename_locale'] = track.ipod_path
      if extInfo[id].has_key("filename_ipod"):
        ef.write("filename_ipod=%s\n" % extInfo[id]['filename_ipod'])
      if extInfo[id].has_key("filename_utf8"):
        ef.write("filename_utf8=%s\n" % extInfo[id]['filename_utf8'])
      if extInfo[id].has_key("filename_locale"):
        ef.write("filename_locale=%s\n" % extInfo[id]['filename_locale'])
      if extInfo[id].has_key("md5_hash") and not forceHash:
        ef.write("md5_hash=%s\n" % extInfo[id]['md5_hash'])
      else:
        hash = fileHash(extInfo[id]['filename_locale'])
        if len(hash) == 40:
          Msg("DEBUG: Hashed %s" % extInfo[id]['filename_locale'], 2)
          if not dryRun:
            ef.write("md5_hash=%s\n" % hash)
      ef.write("transferred=1\n")
    count += 1
  s.Done()
  if not dryRun:
    ef.write("id=xxx\n")
    ef.close()
    Msg( "Wrote extended file, %d tracks" % count, 2)
  else:
    Msg( "Didnt write extended file, %d tracks (dryRun)" % count, 2)

# Read the extended info file from gtkpod
def readExt(extFile):
  global l_itdb
  global dryRun
  global extInfo
  sum = fileHash(options.dbname)

  if os.path.isfile(extFile):
    ef = file(extFile, "r")
    for line in ef.readlines():
      bits = line.strip().split("=", 1)
      key,val = bits
      if key == "version": continue
      elif key == "ituneddb_hash":
        if val != sum:
          Msg("WARN: Checksum for itdb doesn't match", 1)
      elif key == "id":
        chunk_id = val
        if chunk_id != "xxx":
          extInfo[int(chunk_id)] = {}
      elif key == "filename_ipod":
        chunk_fn = val
        extInfo[int(chunk_id)]['filename_ipod'] = chunk_fn
      elif key == "filename_locale":
        chunk_fn = val
        extInfo[int(chunk_id)]['filename_locale'] = chunk_fn
      elif key == "md5_hash":
        chunk_fn = val
        extInfo[int(chunk_id)]['md5_hash'] = chunk_fn
    ef.close()
  else:
    Msg("WARN: No extended info file, will create.", 2)
  for t in gpod.sw_get_tracks(l_itdb):
    if not extInfo.has_key(t.id):
      extInfo[t.id] = {}
      extInfo[t.id]['filename_locale'] = t.ipod_path
    elif not extInfo[t.id].has_key("filename_locale"):
      extInfo[t.id]["filename_locale"] = t.ipod_path
    elif not len(t.ipod_path):
      t.ipod_path = extInfo[t.id]["filename_locale"]
    
def extDel(id, attr):
  global extInfo
  if extInfo.has_key(id):
    if extInfo[id].has_key(attr):
      del extInfo[id][attr]

def extSet(id, attr, value):
  global extInfo
  if not extInfo.has_key(id):
    extInfo[id] = {}
  extInfo[id][attr] = value

# Shifts arg parameters by one (ie strip "ipod" entry)
def argShift(arg):
  ret = []
  if len(arg) < 2: return None
  for a in arg[1:]:
    ret.append(a)
  return ret

# Copy smart playlists from one itdb to the other
def copySPLs(itdb1, itdb2):
  plMap = {}
  splPlaylistRule = False
  for pl in gpod.sw_get_playlists(itdb1):
    if not pl.is_spl:
      continue
    newpl = gpod.itdb_playlist_duplicate(pl)
    gpod.itdb_playlist_add(itdb2, newpl, -1)
    plMap[newpl.id] = pl.id
    Msg("INFO: Copied playlist '%s'" % newpl.name, 1)
    gpod.itdb_spl_update(newpl)
# When copying smart playlists, any that have rules referring to other
# playlists ("Playlist IS <blah") must be updated. Here we change any
# relevent rules to reflect the playlist id in the new playlist
# This still might be broken so we warn the user
  for pl in gpod.sw_get_playlists(itdb2):
    if not pl.is_spl: continue
    for i in xrange(gpod.sw_get_list_len(pl.splrules.rules)):
      rule = gpod.sw_get_rule(pl.splrules.rules, i)
      if rule.field == 0x28: # This is the match playlist field
        orig_rule = gpod.sw_get_rule(playlistById(itdb1,plMap[pl.id]).splrules.rules, i)
        orig_rulepl = playlistById(itdb1,orig_rule.fromvalue)
        rulepl = playlistByName(itdb2,orig_rulepl.name)
        if not rulepl:
          Msg("WARN: Error copying SPL '%s', can't find playlist '%s' referenced in rules. Rebuild this playlist manually!" % (pl.name, orig_rulepl.name), 0)
          continue
        rule.fromvalue = rulepl.id
        rule.tovalue = rulepl.id
        splPlaylistRule = True

    gpod.itdb_spl_update(pl)
  if splPlaylistRule:
    Msg("WARN: One or more smart playlists has rules referring to other playlists.", 1)
    Msg("WARN: Those rules may not have copied correctly. Verify with gtkpod.", 1)

# Delete track, optionally with file too
def deleteTrack(itdb, track,delFile):
  file = gpod.itdb_filename_on_ipod(track)
  if delFile and not dryRun and file:
    if os.path.isfile(file):
      try:
        os.unlink(file)
      except:
        Msg("ERROR: Couldn't delete file %s" % file, 0)
        return False
  gpod.itdb_track_remove_thumbnails(track)
  for pl in gpod.sw_get_playlists(itdb):
    if gpod.itdb_playlist_contains_track(pl, track):
      gpod.itdb_playlist_remove_track(pl, track)
  gpod.itdb_playlist_remove_track(gpod.itdb_playlist_mpl(itdb), track)
  gpod.itdb_track_remove(track)
  return True

# Convert millisecs to "h:m:s"
def prettyTime(time):
  s = time/1000
  m,s=divmod(s,60)
  h,m=divmod(m,60)
  d,h=divmod(h,24)
  ret = "%2.2d:%2.2d" % (m,s)
  if h:
    ret = "%d:%s" % (h, ret)
  return ret

# Convert spl rule date to human readable
def splTime(rule):
  if rule.fromunits == 86400:
    return "%d days" % abs(rule.fromdate)
  if rule.fromunits == 604800:
    return "%d weeks" % abs(rule.fromdate)
  if rule.fromunits == 2628000:
    return "%d months" % abs(rule.fromdate)

# Test if "arg" has minimum size "n", else dump help
def argLen(arg, n):
  if len(arg) < n:
    showhelp()

# Find tracks that match given pattern
# Pattern is one of:
#  <regex>: Regex pattern (if <flags> is set)
#   <file>: List of files to find
#    <dir>: Tracks under <dir>
# 'flags' is a bitmap of the following (OR match):
#   0x1: regex search title
#   0x2: regex search artist
#   0x4: regex search album
def tracksMatch(itdb, pattern, flags):
  retAry = []
  if flags: # Find by regex
    Msg("DEBUG: Finding with regex: %s" % pattern, 2)
    p=re.compile(pattern, re.IGNORECASE)
    for track in gpod.sw_get_tracks(itdb):
      if flags & 0x1:
        if p.search(str(track.title)):
          retAry.append(track)
          continue
      if flags & 0x2:
        if p.search(str(track.artist)):
          retAry.append(track)
          continue
      if flags & 0x4:
        if p.search(str(track.album)):
          retAry.append(track)
          continue
  else: # Find dirs/files that match
    pattern = os.path.abspath(pattern)
    for track in gpod.sw_get_tracks(itdb):
      if track.ipod_path:
        if track.ipod_path.find(pattern) == 0:
          retAry.append(track)
  return retAry

# Create and return a new itdb populated with an empty
# master playlist and an empty Podcast playlist
def makeItdb():
  global dotitdb
  global dryRun
  global newItdb
  if not os.path.isdir(dotitdb) and not dryRun:
    os.mkdir(dotitdb)
  itdb = gpod.itdb_new()
  if not itdb:
    Msg("ERROR: Can't create an itdb, exiting", 0)
    sys.exit(1)
  Msg("INFO: Creating new itdb.", 1)
  mpl = gpod.itdb_playlist_new("Library", 0)
  gpod.itdb_playlist_add(itdb, mpl, -1)
  gpod.itdb_playlist_set_mpl(mpl)
  ppl = gpod.itdb_playlist_new("Podcasts", 0)
  gpod.itdb_playlist_add(itdb, ppl, -1)
  gpod.itdb_playlist_set_podcasts(ppl)
  newItdb = True
  return itdb

# Opens the ITDB, either "local", "ipod" or "both"
# Exits if fail, or returns nothing (sets globals)
def openItdb(which):
  global i_itdb
  global l_itdb
  global ipodDbname
  global dotitdb
  ipodDbname = os.path.join(options.mountpoint,"iPod_Control/iTunes/iTunesDB")
  Msg("DEBUG: Opening itdb %s.." % which, 2)
  if which == "db" or which == "both":
    if not os.path.isfile(options.dbname):
      l_itdb = makeItdb()
    else:
      l_itdb = gpod.itdb_parse_file(options.dbname, None)
      extFile = options.dbname + ".ext"
      readExt(extFile)
    if not l_itdb:
      Msg("ERROR: Failed to read local itdb!", 0)
      sys.exit(1)
  if which == "ipod" or which == "both":
    i_itdb = gpod.itdb_parse(options.mountpoint, None)
    if not os.path.isdir(options.mountpoint):
      Msg("ERROR: Can't find ipod mountpoint %s" % options.mountpoint, 0)
      Msg("ERROR: Specify mountpoint with -m or set mountpoint near the top of script", 0)
      sys.exit(1)
    if not i_itdb:
      Msg("ERROR: Failed to read iPod itdb!", 0)
      sys.exit(1)
  if which == "both":
    readMap() # Read ipod -> local track map db
  Msg("DEBUG: Opened itdb %s" % which, 2)

# Write ITDB to disk, either "ipod" or "db"
# Returns status of itdb_write call
def writeItdb(which):
  global dryRun
  if dryRun:
    Msg("INFO: NOT writing itdb (-n set)", 1)
    return True
  if which == "ipod" or which == "both":
    gpod.itdb_write(i_itdb, None)
  if which == "db" or which == "both":
    gpod.itdb_write_file(l_itdb, options.dbname, None)
    writeExt(False)

# itdb_playlist_by_id is broken, need to do it here
def playlistById(itdb, id):
  for p in gpod.sw_get_playlists(itdb):
    if p.id == id:
      return p
  return NULL

# itdb_playlist_by_name is broken, need to do it here
def playlistByName(itdb, name):
  for p in gpod.sw_get_playlists(itdb):
    if p.name == name:
      return p
  return NULL

def showSPL(pl):
  print "Playlist: %s (0x%x)" % (pl.name, pl.id)
  print " Live update: %s" % ["False", "True"][pl.splpref.liveupdate]
  print " Match %s of the following rules: (%d)" % (["ALL", "ANY"][pl.splpref.checkrules], pl.splpref.checkrules)
  if pl.splpref.checklimits:
    if pl.splpref.limittype == 0x01:
      type = "minutes"
    if pl.splpref.limittype == 0x02:
      type = "Mb"
    if pl.splpref.limittype == 0x03:
      type = "songs"
    if pl.splpref.limittype == 0x04:
      type = "hours"
    if pl.splpref.limittype == 0x05:
      type = "Gb"
    if pl.splpref.limitsort == 0x02:
      sort = "random"
    if pl.splpref.limitsort == 0x03:
      sort = "song name"
    if pl.splpref.limitsort == 0x04:
      sort = "album"
    if pl.splpref.limitsort == 0x05:
      sort = "artist"
    if pl.splpref.limitsort == 0x07:
      sort = "genre"
    if pl.splpref.limitsort == 0x10:
      sort = "most recently added"
    if pl.splpref.limitsort == 0x80000010:
      sort = "least recently added"
    if pl.splpref.limitsort == 0x14:
      sort = "most often played"
    if pl.splpref.limitsort == 0x80000014:
      sort = "least often played"
    if pl.splpref.limitsort == 0x15:
      sort = "most recently played"
    if pl.splpref.limitsort == 0x80000015:
      sort = "least recently played"
    if pl.splpref.limitsort == 0x17:
      sort = "highest rating"
    if pl.splpref.limitsort == 0x80000017:
      sort = "lowest rating"
    print " Limit to %d %s, sorted by %s" % (pl.splpref.limitvalue, type, sort)
  if pl.splpref.matchcheckedonly:
    print " Match only checked tracks"

def showRule(itdb, rule):
  suffix = ""
  if rule.field == 0x02:
    field = "Track title"
    type = "string"
  if rule.field == 0x03:
    field = "Album"
    type = "string"
  if rule.field == 0x04:
    field = "Artist"
    type = "string"
  if rule.field == 0x05:
    field = "Bitrate"
    type = "int"
    suffix = "Kbps"
  if rule.field == 0x06:
    field = "Sample rate"
    type = "int"
    suffix = "Hz"
  if rule.field == 0x07:
    field = "Year"
    type = "int"
  if rule.field == 0x08:
    field = "Genre"
    type = "string"
  if rule.field == 0x09:
    field = "Kind"
    type = "string"
  if rule.field == 0x0a:
    field = "Date modified"
    type = "timestamp"
  if rule.field == 0x0b:
    field = "Track number"
    type = "int"
  if rule.field == 0x0c:
    field = "Size"
    type = "int"
    suffix = " Bytes"
  if rule.field == 0x0d:
    field = "Time"
    type = "int"
  if rule.field == 0x0e:
    field = "Comment"
    type = "string"
  if rule.field == 0x10:
    field = "Date added"
    type = "timestamp"
  if rule.field == 0x12:
    field = "Composer"
    type = "string"
  if rule.field == 0x16:
    field = "Playcount"
    type = "int"
  if rule.field == 0x17:
    field = "Last played"
    type = "timestamp"
  if rule.field == 0x18:
    field = "Disc number"
    type = "int"
  if rule.field == 0x19:
    field = "Rating"
    type = "int"
  if rule.field == 0x1f:
    field = "Compilation"
    type = "int"
  if rule.field == 0x23:
    field = "BPM"
    type = "int"
  if rule.field == 0x27:
    field = "Grouping"
    type = "string"
  if rule.field == 0x28:
    field = "Playlist"
    type = "playlist"

  if rule.action == 0x1: action = "is"
  if rule.action == 0x10: action = "is greater than"
  if rule.action == 0x40: action = "is less than"
  if rule.action == 0x100: action = "is in the range"
  if rule.action == 0x200: action = "is in the last"
  if rule.action == 0x01000001: action = "is"
  if rule.action == 0x01000002: action = "contains"
  if rule.action == 0x01000004: action = "starts with"
  if rule.action == 0x01000008: action = "ends with"

  if rule.action == 0x02000001: action = "is not"
  if rule.action == 0x02000010: action = "is not greater than"
  if rule.action == 0x02000040: action = "is not less than"
  if rule.action == 0x02000100: action = "is not in the range"
  if rule.action == 0x02000200: action = "is not in the last"
  if rule.action == 0x03000001: action = "is not"
  if rule.action == 0x03000002: action = "does not contain"
  if rule.action == 0x03000004: action = "does not start with"
  if rule.action == 0x03000008: action = "does not end with"

  string = " %-15.15s %-20.20s " % (field, action)
  string = string.strip()
  fromvalue = rule.fromvalue
  tovalue = rule.tovalue
  if rule.field == 0x19:
    fromvalue = int(fromvalue/20)
    tovalue = int(tovalue/20)
  if rule.action == 0x100 or rule.action == 0x02000100: # in the range...
    string += " %d%s and %d%s." % (fromvalue, suffix, tovalue, suffix)
  elif rule.action & 0x200: # "in the last... days/weeks"
    string += " %s" % splTime(rule)
  elif rule.field == 0x0d:
    string += " %s" % prettyTime(fromvalue*1000)
  elif rule.field == 0x28:
    string += " %s" % playlistById(itdb, fromvalue).name
  else:
    string += " %d%s" % (fromvalue, suffix)
  print "   " + string
#  print "    field: 0x%x" % rule.field
#  print "    action: 0x%x" % rule.action
#  print "    string: %s" % rule.string
#  print "    fromvalue: 0x%x" % rule.fromvalue
#  print "    fromdate: 0x%x" % rule.fromdate
#  print "    fromunits: 0x%x" % rule.fromunits
#  print "    tovalue: 0x%x" % rule.tovalue
#  print "    todate: 0x%x" % rule.todate
#  print "    tounits: 0x%x" % rule.tounits

#  print "+---+++-------------------------------------------+"
#  print "|      field: 0x%4.4x           action: 0x%8.8x     |"  % (rule.field,rule.action)
#  print "|     string: %25.25s           |"                     % rule.string
#  print "|  fromvalue: 0x%x    fromdate: %4.4d    |"  % (rule.fromvalue,rule.fromdate)
#  print "|  fromunits: 0x%4.4x                           |" % rule.fromunits
#  print "|    tovalue: 0x%x      todate: %4.4d    |"  % (rule.tovalue,rule.todate)
#  print "|    tounits: 0x%4.4x                           |" % rule.tounits

# Make sure all the SPLs look valid. For now, just make sure any rules
# that match a playlist refer to a valid playlist.
def checkSPLs(itdb):
  ret = True
  for p in gpod.sw_get_playlists(itdb):
    if p.is_spl:
      Msg("INFO: Checking playlist '%s' (0x%x) consistency" % (p.name, p.id), 2)
      n = gpod.sw_get_list_len(p.splrules.rules)
      splrules = [gpod.sw_get_rule(p.splrules.rules,i) for i in xrange(n)]
      for i in xrange(gpod.sw_get_list_len(p.splrules.rules)):
        rule = gpod.sw_get_rule(p.splrules.rules, i)
        if rule.field == 0x28:
          rpl = playlistById(itdb, rule.fromvalue) # ** itdb_playlist_by_id broken
          if not rpl:
            Msg("WARN: Rule in playlist '%s' (0x%x) matches unknown playlist 0x%x" % (p.name, p.id, rule.fromvalue), 0)
            ret = False
          else:
            Msg("DEBUG: Rule in SPL '%s' refers to playlist '%s'" % (p.name, rpl.name), 2)
  return ret


# Match ipod files with local DB
def Command_Makemap():
  matches = 0
  ntracks = 0
  openItdb("both")
  readMap()
  s = Spinner()
  titles = {}
  artists = {}
  albums = {}
  tracks = {}
  for ltrack in gpod.sw_get_tracks(l_itdb):
    titles[ltrack.title] = ltrack.id
    artists[ltrack.artist] = ltrack.id
    albums[ltrack.album] = ltrack.id
    tracks[ltrack.id] = [ltrack.title, ltrack.artist, ltrack.album]
  trackTree = gpod.itdb_track_id_tree_create(l_itdb) # Speedup
  for itrack in gpod.sw_get_tracks(i_itdb):
    ntracks += 1
    s.Print()
    for lid in tracks.keys():
      if tracks[lid] == [itrack.title,itrack.artist,itrack.album]:
        isize = fileSize(gpod.itdb_filename_on_ipod(itrack))
        ltrack = gpod.itdb_track_id_tree_by_id(trackTree, lid)
        lsize = fileSize(str(ltrack.ipod_path))
        if lsize != 0 and abs(lsize-isize)/lsize < 0.01:
          setMap(ltrack, itrack)
          matches += 1
        else:
          Msg("Filesize mismatch for %s (%d/%d), ignoring. (%s, %s)" % (itrack.title, isize, lsize, itrack.ipod_path, ltrack.ipod_path), 1)
  s.Done()
  gpod.itdb_track_id_tree_destroy(trackTree)
  writeMap()
  Msg("Matched %d out of %d tracks on iPod" % (matches, ntracks), 1)
  sys.exit(0)

# Handles adding new tracks to the DB
def Command_Add (arg):
  if arg[0] == "ipod":
    openItdb("ipod")
    itdb = i_itdb
    arg = argShift(arg)
    ipodFree = diskFree(options.mountpoint)
    isiPod = True
  else:
    openItdb("db")
    itdb = l_itdb
    isiPod = False
  if not len(arg):
    showhelp()
  if arg[-1] == "podcast":
    isPodcast = True
    arg.pop()
    podcasts = gpod.itdb_playlist_podcasts(itdb)
    if not podcasts:
      print "Error, no podcast playlist!"
      sys.exit(1)
  else: isPodcast = False
  Msg("INFO: Adding files: %s" % arg[1:], 2)
  files = validFiles(arg[1:])
  mpl = gpod.itdb_playlist_mpl(itdb)
  added = 0
  tracksAdded = []
  for file in files:
    skip = 0 # Make sure it's not already in the db
    for tr in gpod.sw_get_tracks(itdb):
      if tr.ipod_path == file:
        Msg("WARN: File already in db: %s" % file, 1)
        skip = 1
        break
    if skip:
      continue
    if eyed3.mp3.isMp3File(file): # Open, make sure it's an mp3
      audioFile = eyed3.mp3.Mp3AudioFile(file, eyed3.id3.ID3_ANY_VERSION)
      tag = audioFile.tag
    else:
      Msg("WARN: %s not an mp3, skipping." % file, 2)
      continue
    if not tag:
      Msg("WARN: No ID3 tags for %s, skipping" % file, 1)
      continue

    filesize = fileSize(file)
    if isiPod:
      if ipodFree - filesize < 5000000: # Leave 5Mb free
        Msg("WARN: Not enough free space for %s, skipping" % track.file, 1)
        continue
      else:
        ipodFree -= filesize
    track = gpod.itdb_track_new() # Create track, set metadata
    track.visible = 1
    track.filetype = "mp3"
    track.ipod_path = file
    track.size = filesize
    # br = audioFile.bit_rate_str() #broken
    # br[0] is true if vbr
    track.bitrate = 128
    #track.tracklen = audioFile.getPlayTime() * 1000 #broken
    track.tracklen = 300000
    track.album = str(tag.album)
    track.artist = str(tag.artist)
    track.title = str(tag.title)
    track.genre = str(tag.genre)
    now = int(time.time()) + 2082844800
    track.time_added = now
    track.rating = int(options.rating) * 20
    if track.title == "":
      Msg("WARN: %s has no id3 title, skipping." % file, 1)
      continue
  # Add it and print result
    gpod.itdb_track_add(itdb, track, -1)
    gpod.itdb_playlist_add_track(mpl, track, -1)
    if isPodcast:
      track.flag1 = 0x02
      track.flag2 = 0x01
      track.flag3 = 0x01
      track.flag4 = 0x01
      track.mark_unplayed = 0x02
      if not len (track.album): # Podcasts must have a valid album
        track.album = track.title
      gpod.itdb_playlist_add_track(podcasts, track, -1)
    if isiPod:
      track.transferred = False
      track.ipod_path = None
      if not dryRun:
        gpod.itdb_cp_track_to_ipod(track, file, None)
        thumb = thumbfile(file)
        if thumb:
          gpod.itdb_track_set_thumbnails(track, thumb)
    tracksAdded.append(track)
    Msg( "INFO: Added file: %s" % file, 1)
    Msg( "          Artist: %s" % track.artist, 2)
    Msg( "           Album: %s" % track.album, 2)
    Msg( "           Title: %s" % track.title, 2)
    Msg( "          Rating: %s" % stars(track), 2)
    added += 1

  if added:
    if isiPod:
      writeItdb("ipod")
    else:
      writeItdb("db")
    Msg("INFO: %d tracks added." % added, 1)
  else:
    Msg("INFO: Nothing added, not writing ITDB", 1)
  if tmpDir:
    for file in os.listdir(tmpDir):
      fl = os.path.join(tmpDir, file)
      os.unlink(fl)
    try:
      os.rmdir(tmpDir)
    except:
      0
  if newItdb:
    Msg("WARN: *** A new local database has been created. *** ", 1)
    Msg("WARN: *** For iPod smart playlist sync, you MUST add playlists with gtkpod ***", 1)
  sys.exit(0)

# Update info from files
def Command_Update (arg):
  Msg( "DEBUG: Will update: %s" % arg, 2)
  openItdb("db")
  itdb = l_itdb
  if len(arg) < 2:
    showhelp()
# First, find matching tracks
  toUpdate = []
  trackTree = gpod.itdb_track_id_tree_create(l_itdb)
  for args in arg[1:]:
    for t in tracksMatch(itdb, args, 0):
      toUpdate.append(t.id)
# Now actually update
  print "The following will be updated:"
  print " Title                          Artist                       Rating "
  for id in toUpdate:
    track = gpod.itdb_track_by_id(itdb, id)
    print " %-30.30s %-30.30s %-5.5s" % (track.title, track.artist, stars(track))
  print "Press enter to continue..."
  ans = sys.stdin.readline().strip()
  for id in toUpdate:
    track = gpod.itdb_track_by_id(itdb, id)
    if track:
      Msg("INFO: Updating %s (%s)" % (track.title, track.artist), 1)
    else:
      Msg("WARN: %s (%s) not found while updating" % (track.title, track.artist), 1)
    file = str(track.ipod_path)
    if eyed3.mp3.isMp3File(file): # Open, make sure it's an mp3
      audioFile = eyed3.mp3.Mp3AudioFile(file, eyed3.id3.ID3_ANY_VERSION)
      tag = audioFile.tag
    else:
      Msg("WARN: %s not an mp3, skipping." % file, 2)
      continue
    if not tag:
      Msg("WARN: No ID3 tags for %s, skipping" % file, 1)
      continue
    track.size = fileSize(file)
    # br = audioFile.bit_rate_str() #broken
    # br[0] is true if vbr
    track.bitrate = 128
    #track.tracklen = audioFile.getPlayTime() * 1000 #broken
    track.tracklen = 300000
    print " %-30.30s %-25.25s %5d %d" % (track.title, track.artist, track.size/1024, track.bitrate)
  writeItdb("db")
  sys.exit(0)

# Delete tracks from ipod/db
def Command_Del (arg):
  global ipodMap
  ipodDB = False
  Msg( "DEBUG: Will del: %s" % arg, 2)
  if arg[0] == "ipod":
    openItdb("both")
    itdb = i_itdb
    ipodDB = True
    arg = argShift(arg)
  else:
    openItdb("db")
    itdb = l_itdb
  if not len(arg):
    showhelp()
# First, find matching tracks for deletion
  toDelete = []
  trackTree = gpod.itdb_track_id_tree_create(l_itdb)
  if ipodDB: 
    for track in gpod.sw_get_tracks(i_itdb):
      if ipodMap.has_key(track.id) and ipodMap[track.id]:
        ltrack = gpod.itdb_track_id_tree_by_id(trackTree, ipodMap[track.id])
        setMap(ltrack, track)
        if extInfo.has_key(ipodMap[track.id]):
          extDel(ipodMap[track.id], "filename_ipod")
    if arg[1] == "notdb": # "notdb" from ipod
      localtracks = []
      for track in gpod.sw_get_tracks(l_itdb):
        localtracks.append(track.id)
      for track in gpod.sw_get_tracks(i_itdb):
        if ipodMap.has_key(track.id):
          if not ipodMap[track.id] in localtracks:
            toDelete.append(track.id)
        else:
          toDelete.append(track.id)
    else: # Regex from ipod
      for regex in arg[1:]:
        Msg("DEBUG: Deleting with regex: %s" % regex, 2)
        for t in tracksMatch(itdb, regex, 0x7):
          toDelete.append(t.id)
  else: # Delete locally by file/dir/regex
    for args in arg[1:]:
      flag = 0x07
      if type != "ipod":
        if os.path.exists(args): flag = 0
        else: flag = 0x7
      for t in tracksMatch(itdb, args, flag):
        toDelete.append(t.id)

# Now actually delete

  if not len(toDelete):
    print "No matching tracks found."
    sys.exit(0)
  print "The following will be deleted:"
  print " Title                          Artist                  Rating   Playcount"
  for id in toDelete:
    track = gpod.itdb_track_by_id(itdb, id)
    print " %-30.30s %-23.23s %-5.5s     %4d" % (track.title, track.artist, stars(track), track.playcount)
  print "Press enter to continue..."
  ans = sys.stdin.readline().strip()
  for id in toDelete:
    track = gpod.itdb_track_by_id(itdb, id)
    if track:
      Msg("INFO: Deleting %s (%s)" % (track.title, track.artist), 1)
      if ipodDB and ipodMap.has_key(track.id):
        delMap(track)
      if not ipodDB:
        if extInfo.has_key(id):
          del extInfo[id]
      deleteTrack(itdb, track, True)
    else:
      Msg("WARN: Track %d not found while deleting" % id, 1)
  if ipodDB:
    gpod.itdb_spl_update_all(i_itdb)
    writeItdb("ipod")
  else:
    writeItdb("db")
  sys.exit(0)

# List all tracks matched by given args
# If "ipod", match on title or artist or album
# if not, match on filename if exists, otherwise title, artist, album
def Command_List (arg):
  Msg("DEBUG: Will list: %s" % arg, 2)
  argstart = 0
  if arg[0] == "ipod":
    type = "ipod"
    openItdb(type)
    itdb = i_itdb
    arg = argShift(arg)
  else:
    type = "db"
    openItdb(type)
    itdb = l_itdb
  if len(arg) < 2:
    arg.append(".*")
    flag = 0x7
  else:
    if type == "ipod":
      flag = 0x7
      argstart = 1
    else:
      flag = 0x7
      argstart = 1
  print "|Title                    | Artist            | Album                | Rating | Added On   | Plays | id  | br |"
  print "+-------------------------+-------------------+----------------------+--------+------------+-------+-----+----+"
  for a in arg[argstart:]:
    if type != "ipod":
      if os.path.exists(a): flag = 0
      else: flag = 0x7
    for track in tracksMatch(itdb, a, flag):
      showFile(track)

  sys.exit(0)

# Dump tracks and itdb info from ipod, merge with local itdb, don't
# overwrite existing unless "-f"
def Command_Dump():
  global ipodMap
  Msg("INFO: Attempting to dump ipod data", 1)
  openItdb("both")
  if not os.path.isdir(options.musicdir) and not dryRun:
    try:
      os.mkdir(options.musicdir)
    except:
      Msg("ERROR: Can't create %s, exiting" % options.musicdir, 0)
      sys.exit(1)
  count = 0
  total = gpod.itdb_tracks_number(i_itdb)
  for track in gpod.sw_get_tracks(i_itdb):
    ipod_file = gpod.itdb_filename_on_ipod(track)
    if not os.path.isfile(ipod_file):
      Msg("WARN: File for %s (%s) not found, skipping." % (track.title, track.artis), 1)
      continue
    album = track.album
    artist = track.artist
    title = track.title
    if ipodMap.has_key(track.id):
      l_track = gpod.itdb_track_by_id(l_itdb, ipodMap[track.id])
      if l_track and l_track.artist == artist and l_track.title == title:
        if options.force:
          Msg("WARN: Duplicate found for %s (%s), copying anyway (-f)" % (title, artist), 1)
        else:
          Msg("WARN: Duplicate found for %s (%s), skipping" % (title, artist), 1)
        continue
    if album == None:
      album = "Unknown"
    if artist == None:
      artist = "Unknown"
    if title == None:
      title = "Unknown"
    extension = os.path.splitext(ipod_file)[1]
    if track.track_nr < 1:
      localFile = "%s%s" % (title, extension)
    else:
      localFile = "%d-%s%s" % (track.track_nr, title, extension)
    localDir = os.path.join(options.musicdir, artist, album)
    if not dryRun and not os.path.isdir(localDir):
      os.makedirs(localDir)
    serial = 1 # Handle identical filenames
    while os.path.isfile(os.path.join(localDir, localFile)):
      localFile = "%d-%s-%d%s" % (track.track_nr, title, serial, extension)
      serial += 1
    newtrack = gpod.itdb_track_duplicate(track)
    newtrack.ipod_path = os.path.join(localDir, localFile)
    if not dryRun:
      try:
        shutil.copyfile(ipod_file, newtrack.ipod_path)
      except:
        Msg("WARN: Error copying %s to '%s', skipping" % (ipod_file, localFile), 1)
        continue
    count += 1
    sys.stdout.write("\r%-30.30s (%-30.30s)      %d/%d     " % (title, artist, count, total))
    sys.stdout.flush()
    gpod.itdb_track_add(l_itdb, newtrack, -1)
    gpod.itdb_playlist_add_track(gpod.itdb_playlist_mpl(l_itdb), newtrack, -1)
    extSet(newtrack.id, "filename_locale", newtrack.ipod_path)
    if options.limit and count >= options.limit:
      Msg("INFO: Reached %d files (--limit set)" % options.limit, 2)
      break
  if count:
    Msg("INFO: %d tracks copied. Now copying smart playlists..." % count, 1)
    copySPLs(i_itdb, l_itdb)
    writeItdb("db")
    Msg("Done!", 1)
  sys.exit(0)

def Command_Evaluate(args):
  if len(args) == 1:
    openItdb("db")
    itdb = l_itdb
  elif args[0] != "ipod" or args[1] != "eval":
    showhelp()
  else:
    openItdb("ipod")
    itdb = i_itdb
  Msg("INFO: Updating smart playlists...", 1)
  gpod.itdb_spl_update_all(itdb)
  if len(args) == 1:
    writeItdb("db")
  else:
    writeItdb("ipod")
  Msg("Done!", 1)
  sys.exit(0)

# Verify that the db and files look sane
def Command_Check (arg):
  Msg( "DEBUG: Will check: %s" % arg, 2)
  global ipodMap
  checkIpod = False
  if len(arg) > 1:
    if arg[0] == "ipod":
      checkIpod = True
      musicDir = os.path.join(options.mountpoint,"iPod_Control/Music")
  songs = []
  dbfiles = []
  insync = True
  modified = False
  s = Spinner()
  if not checkIpod:
    openItdb("db")
    Msg("INFO: Checking playlists...", 1)
    checkSPLs(l_itdb)
    Msg("INFO: Checking tracks...", 1)
    for track in gpod.sw_get_tracks(l_itdb):
      file = str(track.ipod_path)
      mpl = gpod.itdb_playlist_mpl(l_itdb)
      if not file or not os.path.isfile(file):
        Msg("FIXED: File for %s (%s) not found, deleted from db" % (track.title, file), 1)
        deleteTrack(l_itdb, track, False)
        modified = True
        continue
      else:
        fsize = fileSize(file)
        if track.size != fsize:
          Msg("DEBUG: DB size of '%s' (%s)mismatched with file. (file/db: %d/%d)" % (file, track.title, fsize, track.size), 1)
          track.size = fsize
          modified = True
        if fsize < 10:
          Msg("DEBUG: Local file size of '%s' (%s) is zero, deleting" % (file, track.title), 1)
          deleteTrack(l_itdb, track, True)
          modified = True
        sum = fileHash(file)
        if not extInfo.has_key(track.id):
          extInfo[track.id] = {}
          extInfo[track.id]['filename_locale'] = file
        if not extInfo[track.id].has_key("md5_hash"):
          Msg("WARN: Hash for '%s' missing." % track.title, 1)
          extInfo[track.id]['md5_hash'] = None
        if sum != extInfo[track.id]['md5_hash']:
          Msg("WARN: Hash for '%s' invalid, updating." % track.title, 1)
          extInfo[track.id]['md5_hash'] = sum
      if file in dbfiles:
        Msg("FIXED: %s appears twice in db, removing one." % file, 1)
        deleteTrack(l_itdb, track, True)
        modified = True
      else:
        dbfiles.append(file)
      song = "%s:%s:%s" % (track.title, track.album, track.artist)
      if song in songs:
        Msg("INFO: %s (file %s, id %d) duplicated (songname)" % (song, file, track.id), 2)
      songs.append(song)
      if not gpod.itdb_playlist_contains_track(mpl, track):
        print "WARN: %s (%s) not in master playlist. Fixing." % (track.title, track.artist)
        itdb_playlist_add_track(mpl, track, -1)
      s.Print()
  else: # iPod check
    musicfiles = []
    Msg( "INFO: Scanning music files", 1)
    musicfiles = validFiles([musicDir])
    Msg("INFO: Found %d files." % len(musicfiles), 1)
    s.Print()
    mf = []
    for files in musicfiles:
      mf.append(files.lower())
    musicfiles = mf
    count = 0
    yesremove = False
    ids = []
    openItdb("both")
    mpl = gpod.itdb_playlist_mpl(i_itdb)
    Msg("Checking playlists...", 1)
    checkSPLs(i_itdb)
    trackTree = gpod.itdb_track_id_tree_create(l_itdb)
# Make sure each track in the DB is unique, has a valid file, etc
    for track in gpod.sw_get_tracks(i_itdb):
      s.Print()
      file = gpod.itdb_filename_on_ipod(track)
      if file in dbfiles:
        Msg("WARN: %s (file %s) duplicated (filename)" % (track.title, file), 1)
      if file != None:
        realFile = file
        file = file.lower()
        dbfiles.append(file)
      else:
        print "Erk, file is none for %s (%s)" % (track.title, track.ipod_path)
      song = "%s:%s:%s" % (track.title, track.album, track.artist)
      if song in songs:
        Msg("WARN: %s (file %s, id %d) duplicated (songname)" % (song, file, track.id), 1)
      songs.append(song)
      if track.id in ids:
        Msg("WARN: %s (file %s) duplicated (id)" % (song, file), 1)
      ids.append(track.id)
      if not ipodMap.has_key(track.id):
        Msg("WARN: Can't find local id for ipod id %d (%s)" % (track.id, track.title), 1)
      else:
        lt = gpod.itdb_track_id_tree_by_id(trackTree, ipodMap[track.id])
        if not lt:
          Msg("WARN: Can't find local id for ipod id %d (%s)" % (track.id, track.title), 1)
        else:
          if lt.title != track.title or lt.artist != track.artist:
            Msg( "WARN: iPod (%d) has different metadata to local (%d)" % (track.id,lt.id), 1)
      if not gpod.itdb_playlist_contains_track(mpl, track):
        print "WARN: %s (%s) not in master playlist. Fixing." % (track.title, track.artist)
        itdb_playlist_add_track(mpl, track, -1)
      if not file in musicfiles or file == None or not os.path.isfile(realFile):
        print "%s file not found (%s,%s)!\nRemove track from DB? [(Y)es/(N)o/(A)ll] (Yes)" % (file, track.title, track.ipod_path)
        if yesremove:
          print "Yes"
          ans = "y"
        else:
          ans = sys.stdin.readline().strip()
        if ans == "q":
          Msg( "Quitting.", 1)
          modified = False
          break
        if ans == "w":
          Msg( "Finishing..", 1)
          break
        if ans != "n" or ans != "N":
          deleteTrack(i_itdb, track, True)
          modified = True
          Msg("Removed track.", 0)
          if ans == "a":
            yesremove = True
          continue
        insync = False
      else:
        try:
          fsize = fileSize(realFile)
          if track.size != fsize:
            Msg("WARN: '%s' (%s)DB/file size mismatch. (file/db: %d/%d) Fixing." % (file, track.title, fsize, track.size), 2)
            track.size = fsize
            modified = True
        except:
          continue

    for mp3 in musicfiles: # Search for orphaned files on the ipod
      s.Print()
      if not mp3 in dbfiles:
        print mp3, "has no DB entry.\nRemove from disk? [y/N/q]"
        ans = sys.stdin.readline().strip()
        if ans == "y" or ans == "Y":
          os.unlink(mp3)
          print "Removed track."
          continue
        if ans == "q":
          print "Quitting."
          break
        insync = False

  s.Done()
  Msg( "INFO: Found %d files in DB." % len(dbfiles), 1)
  if modified: # Save DB if anything was changed
    if len(arg) > 1:
      gpod.itdb_spl_update_all(i_itdb)
      if insync:
        Msg( "INFO: iPod is clean and matched to PC..", 1)
      else:
        Msg( "WARN: iPod inconsistencies were found!", 0)
        writeItdb("ipod")
    else:
      gpod.itdb_spl_update_all(l_itdb)
      if insync:
        Msg( "INFO: Disk and DB are fully synchronised.", 1)
      else:
        Msg( "WARN: DB and disk are not in sync!", 0)
        writeItdb("db")
    if not dryRun:
      Msg("INFO: Wrote out new itdb", 1)
  Msg( "INFO: Finished check.", 1)
  sys.exit(0)

def Command_Fixart(arg):
  global l_itdb
  global i_itdb
  count = 1
  Msg("Fixing artwork on ipod...", 1)
  openItdb("ipod")
  s = Spinner()
  for track in gpod.sw_get_tracks(i_itdb):
    sys.stdout.write(" %-4.4d done   " % count)
    sys.stdout.flush()
    if not options.dryrun:
      thumb = thumbfile(gpod.itdb_filename_on_ipod(track))
      if thumb:
        gpod.itdb_track_set_thumbnails(track, thumb)
    s.Print()
    count += 1
  sys.stdout.write('\n')
  writeItdb("ipod")
  s.Done()
  if tmpDir:
    for file in os.listdir(tmpDir):
      fl = os.path.join(tmpDir, file)
      os.unlink(fl)
    try:
      os.rmdir(tmpDir)
    except:
      0
  Msg("Done!", 1)
  sys.exit(0)

def Command_wrExt(arg):
  global l_itdb
  openItdb("db")
  writeExt(True)
  sys.exit(0)

def Command_Diff (arg):
  global l_itdb
  global i_itdb
  global ipodMap
  count = 0
  openItdb("both")
  Msg("INFO: Showing iPod/local track differences", 2)
  trackTree = gpod.itdb_track_id_tree_create(l_itdb)
  print "| Title                   | Artist              | Changes                  |"
  print "+-------------------------+---------------------+--------------------------+"
  for itrack in gpod.sw_get_tracks(i_itdb):
    ltrack = None
    if ipodMap.has_key(itrack.id):
      ltrack = gpod.itdb_track_id_tree_by_id(trackTree, ipodMap[itrack.id])
    if not ltrack:
      Msg( "WARN: Can't find local track for id %d (%s)" % (itrack.id, itrack.title), 1)
      continue
    chstr = " %-25.25s %-21.21s (" % (ltrack.title, ltrack.artist)
    tchanged = 0
    if ltrack.id:
      if ltrack.artist != itrack.artist or ltrack.title != itrack.title:
        Msg("WARN: (%d) %s (%s) on ipod not matched with db (%s, %s), skipping." % (ltrack.id, itrack.title, itrack.artist, ltrack.title, ltrack.artist), 1)
        continue
      if ltrack.rating != itrack.rating:
        chstr += "%-5.5s -> %-5.5s, " % (stars(ltrack), stars(itrack))
        tchanged = 1
      if ltrack.playcount != itrack.playcount:
        chstr += "%3d -> %3d plays " % (ltrack.playcount, itrack.playcount)
        tchanged = 1
      if ltrack.time_played != itrack.time_played:
        lplayed = time.strftime("%d %b", time.gmtime(ltrack.time_played-2082844800))
        iplayed = time.strftime("%d %b", time.gmtime(itrack.time_played-2082844800))
        chstr += "%s -> %s last played" % (lplayed, iplayed)
        tchanged = 1
      if tchanged:
        chstr += ")"
        Msg(chstr,0)
        count += 1
  if not count:
    print "All tracks are in sync."
  else:
    print "%d tracks have updated information." % count
  sys.exit(0)

def Command_Info(arg):
  global i_itdb
  Msg("WARN: Info command not yet implemented", 1)
  sys.exit(0)

def Command_Playlist(arg):
  Msg("DEBUG: Playlist command: %s" % arg, 2)
  global l_itdb
  global i_itdb
  if arg[0] == "ipod": 
    openItdb("ipod")
    arg = argShift(arg)
    itdb = i_itdb
    where = "ipod"
  else: 
    openItdb("db")
    itdb = l_itdb
    where = "db"
  if len(arg) > 1:
    cmd = arg[1]
    if cmd == "list":
      if len(arg) > 2:
        playlist = gpod.itdb_playlist_by_name(itdb, arg[2])
        if not playlist:
          Msg("ERROR: Playlist '%s' doesn't exist!" % arg[2], 0)
          sys.exit(1)
        action = "list"
      else:
        action = "showlists"
    elif cmd == "rules":
      if len(arg) > 2:
        playlist = gpod.itdb_playlist_by_name(itdb, arg[2])
        if not playlist:
          Msg("ERROR: Playlist '%s' doesn't exist!" % arg[2], 0)
          sys.exit(1)
        if playlist.is_spl:
          action = "showspl"
        else:
          Msg("WARN: Playlist '%s' is not a smart playlist." % arg[2], 1)
          sys.exit(1)
      else:
        action = "showallspls"
    elif cmd == "play":
      argLen(arg, 3)
      action = "play"
      playlist = gpod.itdb_playlist_by_name(itdb, arg[2])
    elif cmd == "create":
      argLen(arg, 3)
      action = "create"
      name = arg[2]
      if len(arg) == 4:
        if arg[3] == "podcast": type = "podcast"
      else: type = ""
    elif cmd[0:3] == "del":
      argLen(arg, 3)
      action = "delete"
    elif cmd == "remove":
      argLen(arg, 4)
      action = "remove"
    elif cmd == "add":
      argLen(arg, 4)
      action = "addto"
    else:
      showhelp()
  if action == "showlists":
    print "| Name              | Items | Size   |Smart? |"
    print "+-------------------+-------+--------+-------+"
    for playlist in gpod.sw_get_playlists(itdb):
      size = 0
      for track in gpod.sw_get_playlist_tracks(playlist):
        size += track.size
      if playlist.is_spl:
        isspl = "Yes"
      else:
        isspl = "No"
      print " %-19.19s  %4d   %5dMb    %3s " % (playlist.name, len(gpod.sw_get_playlist_tracks(playlist)), size/1024/1024, isspl)
  elif action == "play":
    for track in gpod.sw_get_playlist_tracks(playlist):
      file = track.ipod_path
      print "Track: %s (%s) Rating: %s Playcount: %d" % (track.title, track.artist, stars(track), track.playcount)
      if not os.path.isfile(file):
        Msg("WARN: Can't find %s, skipping" % file, 1)
        continue
      ret = os.system("play '%s'" % file)
      track.playcount += 1
      track.time_played = int(time.time()) + 2082844800
      time.sleep(2)
  elif action == "list":
    print "Tracks in playlist '%s':" % playlist.name
    print "| Title                       | Artist            | Rating | Length |Plays|"
    print "+-----------------------------+-------------------+--------+--------+-----+"
    for t in gpod.sw_get_playlist_tracks(playlist):
      print " %-30.30s %-20.20s %-5.5s %8s   %3d" % (t.title, t.artist, stars(t), prettyTime(t.tracklen),t.playcount)
    sys.exit(0)
  elif action == "showspl" or action == "showallspls":
    lists = []
    if action == "showspl":
      lists = [ playlist ]
    else:
      lists = gpod.sw_get_playlists(itdb)
    for playlist in lists:
      if playlist.is_spl:
        n = gpod.sw_get_list_len(playlist.splrules.rules)
        splrules = [gpod.sw_get_rule(playlist.splrules.rules,i) for i in xrange(n)]
        showSPL(playlist)
        for i in xrange(gpod.sw_get_list_len(playlist.splrules.rules)):
            rule = gpod.sw_get_rule(playlist.splrules.rules, i)
            showRule(itdb, rule)
  elif action == "create":
    if gpod.itdb_playlist_by_name(itdb, name):
      Msg("ERROR: Playlist '%s' already exists!" % name, 0)
      sys.exit(1)
    playlist = gpod.itdb_playlist_new(name, False)
    gpod.itdb_playlist_add(itdb, playlist, -1)
    if type == "podcast": 
      gpod.itdb_playlist_set_podcasts(playlist)
      ispodcast = " and set as Podcast list"
    else: ispodcast = ""
    writeItdb(where)
    Msg("INFO: Created playlist '%s' %s" % (name, ispodcast), 1)
  elif action == "delete":
    name = arg[2]
    playlist = gpod.itdb_playlist_by_name(itdb, name)
    if not playlist:
      Msg("ERROR: Playlist '%s' doesn't exists!", 0)
      sys.exit(1)
    tracks = gpod.sw_get_playlist_tracks(playlist)
    if len(tracks):
      if not options.force:
        askIfOk( "WARN: Playlist '%s' contains %d tracks. Continue? " % (name, len(tracks)))
    if len(tracks) and options.deleteFiles:
      for track in tracks:
        Msg("INFO: Deleting playlist tracks and files...", 1)
        deleteTrack(itdb, track, True)
    gpod.itdb_playlist_remove(playlist)
    writeItdb(where)
    Msg("INFO: Deleted playlist '%s'" % name, 1)
  elif action == "addto":
    name = arg[2]
    tracks = []
    playlist = gpod.itdb_playlist_by_name(itdb, name)
    if not playlist:
      Msg("ERROR: Playlist '%s' doesn't exist!" % name, 0)
      sys.exit(1)
    for pattern in arg[3:]:
      for track in tracksMatch(itdb, pattern, 0x7):
        tracks.append(track)
    if not tracks:
      Msg("WARN: No tracks matching '%s'" % arg[3:], 1)
      sys.exit(0)
    pltracks = gpod.sw_get_playlist_tracks(playlist)
    tracksadded = []
    for t in tracks:
      if t in pltracks: continue
      gpod.itdb_playlist_add_track(playlist, t, -1)
      tracksadded.append(t)
    print "Added the following tracks to '%s':" % name
    for t in tracksadded:
      print " %-30.30s %-30.30s %-5.5s" % (t.title, t.artist, stars(t))
    writeItdb(where)
  elif action == "remove":
    name = arg[2]
    tracks = []
    playlist = gpod.itdb_playlist_by_name(itdb, name)
    if not playlist:
      Msg("ERROR: Playlist '%s' doesn't exist!" % name, 0)
      sys.exit(1)
    for pattern in arg[3:]:
      for track in tracksMatch(itdb, pattern, 0x7):
        tracks.append(track)
    if not tracks:
      Msg("WARN: No tracks matching '%s'" % arg[3:], 1)
      sys.exit(0)
    pltracks = gpod.sw_get_playlist_tracks(playlist)
    tracksremoved = []
    print "Removng the following tracks from '%s':" % name
    for t in tracks:
      for tr in pltracks:
        if tr.id == t.id:
          break
      else:
        continue
      gpod.itdb_playlist_remove_track(playlist, t)
      print " %-30.30s %-30.30s %-5.5s" % (t.title, t.artist, stars(t))
      if options.deleteFiles:
        Msg("INFO: Deleting %s..." % file, 1)
        deleteTrack(itdb, t, True)
    writeItdb(where)
  sys.exit(0)


# Python cookbook 1.9 
def Command_Sync (arg):
  Msg( "DEBUG: Will sync: %s" % arg, 2)
  Msg( "DEBUG: Limiting to: %d" % options.limit, 2)
  global l_itdb
  global i_itdb
  global ipodDbname
  global dotitdb
  global ipodMap
  global tmpDir
  meta = False
  if len(arg) > 1:
    if arg[1] == "meta":
      meta = True
    else:
      showhelp()
  openItdb("both")
  if not checkSPLs(i_itdb):
    Msg("WARN: *** Playlist inconsistencies in the iPod DB", 0)
  if not checkSPLs(l_itdb):
    Msg("WARN: *** Playlist inconsistencies in the local DB", 0)
  Msg("DEBUG: Merging playcount and ratings...", 2)
  trackTree = gpod.itdb_track_id_tree_create(l_itdb)
  # Copy iPod ratings, playcount info to local db
  changed = 0
  for itrack in gpod.sw_get_tracks(i_itdb):
    ltrack = None
    if ipodMap.has_key(itrack.id):
      ltrack = gpod.itdb_track_id_tree_by_id(trackTree, ipodMap[itrack.id])
    if not ltrack:
      Msg( "WARN: Can't find local track for id %d (%s)" % (itrack.id, itrack.title), 1)
      continue
    setMap(ltrack, itrack)
    chstr = "DEBUG: %-30.30s (" % ltrack.title
    tchanged = 0
    if ltrack.id:
      if ltrack.artist != itrack.artist or ltrack.title != itrack.title:
        Msg("WARN: (%d) %s (%s) on ipod not matched with db (%s, %s), skipping." % (ltrack.id, itrack.title, itrack.artist, ltrack.title, ltrack.artist), 1)
        continue
      if ltrack.rating != itrack.rating:
        chstr += "%s -> %s, " % (stars(ltrack), stars(itrack))
        ltrack.rating = itrack.rating
        tchanged = 1
      if ltrack.playcount != itrack.playcount:
        chstr += "%d -> %d plays" % (ltrack.playcount, itrack.playcount)
        ltrack.playcount = itrack.playcount
        tchanged = 1
      if ltrack.time_played != itrack.time_played:
        ltrack.time_played = itrack.time_played
        tchanged = 1
      if ltrack.mark_unplayed != itrack.mark_unplayed:
        if itrack.mark_unplayed < 255:
          ltrack.mark_unplayed = itrack.mark_unplayed
          tchanged = 1
      if ltrack.bookmark_time != itrack.bookmark_time:
        ltrack.bookmark_time = itrack.bookmark_time
        tchanged = 1
      if tchanged:
        changed += 1
        chstr += ")"
        Msg(chstr,2)

  if changed:
    Msg("INFO: Merged stats from %d tracks" % changed, 1)

  # Evaluate local playlists
  gpod.itdb_spl_update_all(l_itdb)

  writeItdb("db")
  if meta:
    Msg("INFO: Metadata sync done.", 1)
    sys.exit(0)

  copytoipod = []
  delfromipod = []
  numtocopy = 0
  totalsize = 0
  
  Msg("DEBUG: Determining tracks to copy to ipod", 2)

  # Get tracks to copy from local playlists
  for playlist in gpod.sw_get_playlists(l_itdb):
    # Copy from playlists in ipod, but not master
    if gpod.itdb_playlist_is_mpl(playlist):
      continue
    for pl in gpod.sw_get_playlists(i_itdb):
      if pl.name == playlist.name:
        break
    else:
      continue
    if playlist.is_spl:
      Msg("Playlist: %s (%d tracks)" % (playlist.name, gpod.itdb_playlist_tracks_number(playlist)), 1)
      for track in gpod.sw_get_playlist_tracks(playlist):
        tid = track.id
        if not tid in copytoipod:
          copytoipod.append(tid)
          tr = gpod.itdb_track_id_tree_by_id(trackTree, tid)
          totalsize += tr.size
          numtocopy += 1

  podcastlist = []
  podcasts = gpod.itdb_playlist_podcasts(l_itdb)
  if podcasts:
    Msg("Playlist: %s (%d tracks)" % (podcasts.name, gpod.itdb_playlist_tracks_number(podcasts)), 1)
    for track in gpod.sw_get_playlist_tracks(podcasts):
      if track.mark_unplayed == 0x02:
        if not track.id in copytoipod:
          copytoipod.append(track.id)
          totalsize += track.size
          numtocopy += 1
          podcastlist.append(track.id)
  if not gpod.itdb_playlist_podcasts(i_itdb):
    Msg("WARN: iPod doesn't have a Podcast playlist", 1)

  # If ipod tracks arent in 'to copy' list, remove them
  stalebytes = 0
  for itrack in gpod.sw_get_tracks(i_itdb):
    if ipodMap.has_key(itrack.id):
      if not ipodMap[itrack.id] in copytoipod:
        delfromipod.append(itrack)
        stalebytes += itrack.size
    else:
      delfromipod.append(itrack)

  Msg("INFO: Will remove %d stale tracks from iPod (%d Mb)" % (len(delfromipod), stalebytes/1024/1024), 1)

  # Determine what tracks to copy to ipod
  trackstoipod = []
  copybytes = totalsize
  for tid in copytoipod:
    for itrack in gpod.sw_get_tracks(i_itdb):
      if ipodMap.has_key(itrack.id):
        if tid == ipodMap[itrack.id]:
          numtocopy -= 1
          copybytes -= itrack.size
          break  # Skip if track's already on ipod
    else:
      trackstoipod.append(tid)

  fs_blocks = diskSpace(options.mountpoint)
  Msg( "INFO: Preparing to copy %d new tracks (%d Mb, total %d Mb)" % (numtocopy, copybytes/1024/1024, totalsize/1024/1024), 1)
  if totalsize > (fs_blocks - 13000000):
    Msg( "WARN: Insufficient space to copy (need %dMb, have %d)" % (totalsize/1024/1024, fs_blocks/1024/1024), 0)

  # Find and warn about duplicates
  filess = []
  for tid in copytoipod:
    track = gpod.itdb_track_id_tree_by_id(trackTree, tid)
    if track.ipod_path in filess:
      Msg("WARN: Duplicate track: %s (%s)" % (track.ipod_path, track.title), 1)
    filess.append(track.ipod_path)

  print "Hit enter to continue..."
  undef = sys.stdin.readline()

  # Write local itdb
  writeItdb("local")

  # Delete old tracks from ipod
  delsize = 0
  for itrack in delfromipod:
    if ipodMap[itrack.id]:
      itfile = gpod.itdb_filename_on_ipod(itrack)
      Msg( "DEBUG: Removing %s (%s)" % (itrack.title, itrack.ipod_path), 2)
      str = "Removing %-70.70s" % itrack.title
      sys.stdout.write(str.strip() + "\r")
      sys.stdout.flush()
      delsize += itrack.size
      delMap(itrack)
      extDel(itrack.id, "filename_ipod")
      deleteTrack(i_itdb, itrack, True)

  fs_free = diskFree(options.mountpoint)
  if dryRun:
    fs_free = fs_free + delsize

  # Copy track to ipod, skip if already there
  written = []
  count = 0
  for tid in trackstoipod:
    if tid in written:
      Msg("WARN: Hmm..already wrote track id %d, skipping" % tid, 2)
    written.append(tid)
    track = gpod.itdb_track_id_tree_by_id(trackTree, tid)
    count += 1
    tfile = track.ipod_path
    if not os.path.isfile(tfile):
      Msg("WARN: Can't find %s, skipping \n\n" % tfile, 1)
      continue
    if 0 and fs_free - track.size < 24000000:  # Leave 24Mb free on ipod
      Msg("WARN: No space left while writing %s" % track.title, 0)
      break
    fs_free -= track.size
    t2 = gpod.itdb_track_duplicate(track)
    t2.ipod_path = None      # Clear path so libgpod does it for me
    t2.transferred = False   # libgpod only transfers if this is false
    gpod.itdb_track_add(i_itdb, t2, -1)
    gpod.itdb_playlist_add_track(gpod.itdb_playlist_mpl(i_itdb), t2, -1)
    if track.id in podcastlist:
      gpod.itdb_playlist_add_track(gpod.itdb_playlist_podcasts(i_itdb), t2, -1)
      Msg("INFO: Added '%s' to podcast playlist" % track.title, 1)
    if not dryRun:
      gpod.itdb_cp_track_to_ipod(t2, tfile, None)
    thumb = thumbfile(track.ipod_path)
    if thumb:
      gpod.itdb_track_set_thumbnails(t2, thumb)
      wthumb = "( +thumb )"
    else:
      wthumb = ""
    Msg( "INFO: Copying: %s (%s) %s (%d/%d)" % (track.title, track.artist, wthumb, count, numtocopy), 1)
    setMap(track, t2) # Set ipod->local mapping
    extSet(track.id, "filename_ipod", t2.ipod_path)
    if not count % 50:
      Msg("DEBUG: Flushing after 50 tracks..\n", 2)
      gpod.itdb_spl_update_all(i_itdb)
      writeItdb("ipod")
    if options.limit > 0 and count >= options.limit:
      Msg("INFO: Stopping after %d tracks (--limit specified)" % count, 1)
      break

  Msg( "DEBUG: Updating playlists...", 2)
  gpod.itdb_spl_update_all(i_itdb)
  Msg( "INFO: Writing ITDB and syncing disk..", 1)
  writeItdb("ipod")
  writeExt(False)
  writeMap()
  if not dryRun:
    Msg( "DEBUG: Backing up iPod itdb...", 2)
    shutil.copyfile(ipodDbname, os.path.join(dotitdb, "iTunesDB.ipod"))
  if not dryRun:
    Msg( "DEBUG: Clearing temporary files...", 2)
    for file in os.listdir(tmpDir):
      fl = os.path.join(tmpDir, file)
      os.unlink(fl)
    try:
      os.rmdir(tmpDir)
    except:
      0
      # nothing
  gpod.itdb_track_id_tree_destroy(trackTree)
  Msg( "Done!", 1)
  sys.exit(0)



def showhelp():
  parser.print_help()
  sys.exit(2)

usage = """
%prog [options] <command> [args]

command is one of:

  sync [meta]                   - Sync iPod and local DB
                                  - meta: Only merge metadata from ipod
  ipod add <files|dirs> [podcast]
                                - Add <files|dirs> to iPod (but not local db)
                                  If [podcast], set as podcast and add to
                                  podcast playlist
  ipod del <notdb|pattern>      - Delete tracks (+files) from iPod.
                                  - notdb: all fcksiles not in local db
                                  - pattern: titles matching regex pattern
  ipod list <pattern>           - List tracks with titles, artist or album
                                  matching given regex pattern
  ipod playlist create <name> [podcast]
                                - Create a standard playlist called <name>,
                                  and optionally set it to be the podcast
                                  playlist
  ipod playlist list [name]     - Show playlists [details for <name>]
  ipod playlist add <name> <tracks>
                                - Add <tracks> to playlist <name>. Tracks
                                 must exist on ipod (see 'add') and are
                                  regex matched by title/artist/album
  ipod playlist del <name>      - Delete playlist <name>. Use --del-files
                                  option to also delete files/tracks
  ipod playlist remove <name> <tracks>
                                - Remove tracks matching <tracks> from
                                  playlist <name>. Use --del-files option
                                  to also delete files.tracks
  ipod dump                     - Dump tracks and itdb from iPod. Merges
                                  db info to local db and copies files
  ipod check                    - Check ipod for orphans, dupes, etc
  ipod makemap                  - Create mapping between ipod and local db
  ipod eval                     - Evaluate and save smart playlists
  ipod fixart                   - Repair artwork on iPod (re-extract from mp3s)
  add <files|dirs>              - Add mp3s to local itdb
                                  - <files> to add given files
                                  - <dir> to add dir recursively
  del <files|dirs|pattern>      - Delete tracks from local db (not files)
                                  - <files> are filenames as in db
                                  - <dirs> looks for tracks under <dirs>
                                  - titles matching regex pattern
  list <files|dirs|pattern>       - List info for file, dir or regex "pattern"
  playlist create <name> [podcast]
                                - Create a standard playlist called <name>,
                                  optionally set as podcast playlist
  playlist list [name]          - Show playlists [tracks in it with <name>]
  playlist rules <name>         - Show rules for smart playlist <name>
  playlist add <name> <tracks>  - Add <tracks> to playlist <name>. Tracks
                                  must exist on ipod (see 'add') and are
                                  regex matched by title/artist/album
  playlist del <name>           - Delete playlist <name>. Use --del-files
                                  option to also delete files/tracks
  playlist remove <name> <tracks>
                                - Remove tracks matching <tracks> from
                                  playlist <name>. Use --del-files option
                                  to also delete files.tracks
  eval                          - Evaluate and save smart playlists
  check                         - Check DB for dangling tracks, dupes, etc
  diff                          - Show tracks which have changed rating,
                                  playcount or playtime on iPod
  update <files|dirs>           - Hunts for tracks in <files|dirs> and
                                  updates database with new info. Useful if
                                  you have a new rip of a track.
"""

parser = OptionParser(usage=usage, version="%prog 1.0")
parser.add_option("-m", "--mountpoint", dest="mountpoint",
                 default=mountpoint,
                 help="iPod is mounted at MOUNTPOINT. "
                 "Default: %default ")
parser.add_option("-l", "--localdb", dest="dbname",
                 default=os.path.join(dotitdb, "local_0.itdb"),
                 help="Use LOCALDB as local itdb. "
                 "Default: $HOME/.gtkpod/local_0.itdb", metavar="LOCALDB")
parser.add_option("-M", "--musicdir", dest="musicdir",
                 default=os.path.join(dotitdb, "musicdump"),
                 help="Dump tracks to MUSICDIR (for dump command). "
                      "Default: $HOME/.gtkpod/musicdump")
parser.add_option("-r", "--rating", dest="rating",
                 type="int", default=0,
                 help="Add rating to new tracks (add command only)")
parser.add_option("--del-files", action="store_true", dest="deleteFiles",
                 help="With local 'del' command, also delete files")
parser.add_option("--limit", dest="limit", type="int", default=0,
                 help="Limit to <limit> files when adding/syncing/dumping")
parser.add_option("-v", "--verbose", action="store_true",
                 dest="verbose", help="Verbose output")
parser.add_option("-q", "--quiet", action="store_true",
                 dest="quiet", help="Quiet, only print errors")
parser.add_option("-f", "--force", action="store_true",
                 dest="force", help="Force overwrites (dump command)")
parser.add_option("-n", "--dry-run", action="store_true",
                 dest="dryrun", help="Dry run, don't actually write anything.")
(options, args) = parser.parse_args()

if len(args) < 1:
  showhelp()

verbose = 1
newItdb = False
if options.quiet: verbose = 0
if options.verbose: verbose = 2

dryRun = options.dryrun
if dryRun: Msg("INFO: -n set, NOT writing anything.", 2)

ipodMap = {}
extInfo = {}
tmpDir = None

# Python cookbook, 1.7

if args[0] == "sync": Command_Sync(args)
if args[0] == "update": Command_Update(args)

n = 0
if args[0] == "ipod": n += 1
if len(args) < n: showhelp()
if args[n] == "dump": Command_Dump()
if args[n] == "add": Command_Add(args)
if args[n][0:3] == "del": Command_Del(args)
if args[n] == "list": Command_List(args)
if args[n] == "makemap": Command_Makemap()
if args[n] == "check": Command_Check(args)
if args[n] == "eval": Command_Evaluate(args)
if args[n] == "diff": Command_Diff(args)
if args[n] == "fixart": Command_Fixart(args)
if args[n] == "playlist": Command_Playlist(args)
if args[n] == "info": Command_Info(args)
if args[n] == "writeext": Command_wrExt(args)
showhelp()

