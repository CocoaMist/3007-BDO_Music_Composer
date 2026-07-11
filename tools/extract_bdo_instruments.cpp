#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include "../_tools/PAZ-Unpacker/Crypt.h"

namespace fs = std::filesystem;

struct Info {
  uint32_t crc, folder, name, offset, packed, original;
};

bool is_instrument_bank(const std::string& path) {
  return path.starts_with("sound2022/windows/midi_instrument_") && path.ends_with(".bnk");
}

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: extract_bdo_instruments <Paz folder> <output folder>\n";
    return 2;
  }
  std::string base(argv[1]);
  if (!base.empty() && base.back() != '\\') base.push_back('\\');
  fs::path output(argv[2]);
  std::ifstream meta(base + "pad00000.meta", std::ios::binary);
  if (!meta) {
    std::cerr << "Cannot open pad00000.meta\n";
    return 1;
  }

  uint32_t version, count;
  meta.read(reinterpret_cast<char*>(&version), 4);
  meta.read(reinterpret_cast<char*>(&count), 4);
  uint8_t key[] = {0x51, 0xF3, 0x0F, 0x11, 0x04, 0x24, 0x6A, 0x00};
  kukdh1::CryptICE ice(key, 8);
  uint32_t extracted = 0;

  for (uint32_t index = 0; index < count; ++index) {
    uint32_t number, crc, size;
    meta.read(reinterpret_cast<char*>(&number), 4);
    meta.read(reinterpret_cast<char*>(&crc), 4);
    meta.read(reinterpret_cast<char*>(&size), 4);
    char archive_name[32];
    sprintf_s(archive_name, "PAD%05u.PAZ", number);
    std::ifstream archive(base + archive_name, std::ios::binary);
    if (!archive) continue;

    uint32_t archive_crc, file_count, path_len;
    archive.read(reinterpret_cast<char*>(&archive_crc), 4);
    archive.read(reinterpret_cast<char*>(&file_count), 4);
    archive.read(reinterpret_cast<char*>(&path_len), 4);
    std::vector<Info> infos(file_count);
    archive.read(reinterpret_cast<char*>(infos.data()), file_count * sizeof(Info));
    std::vector<uint8_t> encrypted_paths(path_len);
    archive.read(reinterpret_cast<char*>(encrypted_paths.data()), path_len);
    uint8_t* raw_paths = nullptr;
    uint32_t raw_len = 0;
    ice.decrypt(encrypted_paths.data(), path_len, &raw_paths, &raw_len);
    std::vector<std::string> paths;
    for (uint32_t pos = 0; pos < raw_len;) {
      paths.emplace_back(reinterpret_cast<char*>(raw_paths) + pos);
      pos += static_cast<uint32_t>(paths.back().size()) + 1;
    }

    for (const auto& info : infos) {
      if (info.folder >= paths.size() || info.name >= paths.size()) continue;
      std::string path = paths[info.folder] + paths[info.name];
      if (!is_instrument_bank(path)) continue;
      std::vector<uint8_t> encrypted(info.packed);
      archive.seekg(info.offset);
      archive.read(reinterpret_cast<char*>(encrypted.data()), info.packed);
      uint8_t* decrypted = nullptr;
      uint32_t decrypted_len = 0;
      ice.decrypt(encrypted.data(), info.packed, &decrypted, &decrypted_len);
      std::vector<uint8_t> result(info.original);
      if (info.original > info.packed || decrypted[0] == 0x6E || decrypted[0] == 0x6F) {
        kukdh1::decompress(decrypted, result.data());
      } else {
        result.assign(decrypted, decrypted + info.original);
      }
      free(decrypted);
      fs::path target = output / fs::path(path);
      fs::create_directories(target.parent_path());
      std::ofstream save(target, std::ios::binary);
      save.write(reinterpret_cast<char*>(result.data()), result.size());
      std::cout << target.string() << '\n';
      ++extracted;
    }
    free(raw_paths);
  }
  std::cerr << "Extracted " << extracted << " instrument soundbanks from meta version " << version << "\n";
}
