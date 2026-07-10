#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include "../_tools/PAZ-Unpacker/Crypt.h"

struct Info { uint32_t crc, folder, name, offset, packed, original; };
bool audio(const std::string& s) {
  static const std::vector<std::string> extensions = {".wem", ".wav", ".ogg", ".mp3", ".fsb", ".bnk", ".acb", ".hca", ".awb", ".wma"};
  for (const auto& extension : extensions)
    if (s.size() >= extension.size() && s.compare(s.size() - extension.size(), extension.size(), extension) == 0) return true;
  return false;
}
int main(int argc, char** argv) {
  if (argc != 3) { std::cerr << "usage: list_bdo_paz_audio <Paz folder> <output TSV>\n"; return 2; }
  std::string base(argv[1]); if (!base.empty() && base.back() != '\\') base.push_back('\\');
  std::ifstream meta(base + "pad00000.meta", std::ios::binary);
  uint32_t version, count; meta.read(reinterpret_cast<char*>(&version), 4); meta.read(reinterpret_cast<char*>(&count), 4);
  std::ofstream out(argv[2], std::ios::binary); out << "paz\toffset\tpacked_size\toriginal_size\tpath\n";
  uint8_t key[] = {0x51, 0xF3, 0x0F, 0x11, 0x04, 0x24, 0x6A, 0x00}; kukdh1::CryptICE ice(key, 8);
  uint64_t matches = 0;
  for (uint32_t archive_no = 0, crc, size; archive_no < count; ++archive_no) {
    uint32_t number; meta.read(reinterpret_cast<char*>(&number), 4); meta.read(reinterpret_cast<char*>(&crc), 4); meta.read(reinterpret_cast<char*>(&size), 4);
    char filename[32]; sprintf_s(filename, "PAD%05u.PAZ", number);
    std::ifstream file(base + filename, std::ios::binary); if (!file) continue;
    uint32_t hdr_crc, file_count, path_len; file.read(reinterpret_cast<char*>(&hdr_crc), 4); file.read(reinterpret_cast<char*>(&file_count), 4); file.read(reinterpret_cast<char*>(&path_len), 4);
    std::vector<Info> infos(file_count); file.read(reinterpret_cast<char*>(infos.data()), file_count * sizeof(Info));
    std::vector<uint8_t> encrypted(path_len); file.read(reinterpret_cast<char*>(encrypted.data()), path_len);
    uint8_t* raw = nullptr; uint32_t raw_len = 0; ice.decrypt(encrypted.data(), path_len, &raw, &raw_len);
    std::vector<std::string> paths; for (uint32_t pos = 0; pos < raw_len;) { paths.emplace_back(reinterpret_cast<char*>(raw) + pos); pos += static_cast<uint32_t>(paths.back().size()) + 1; }
    for (const auto& info : infos) if (info.folder < paths.size() && info.name < paths.size()) {
      std::string path = paths[info.folder] + paths[info.name];
      if (audio(path)) { out << number << '\t' << info.offset << '\t' << info.packed << '\t' << info.original << '\t' << path << '\n'; ++matches; }
    }
    free(raw);
  }
  std::cerr << "meta version " << version << "; audio entries " << matches << "\n";
}
