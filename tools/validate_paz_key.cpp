#include <cstdint>
#include <fstream>
#include <iostream>
#include <vector>
#include "../_tools/PAZ-Unpacker/Crypt.h"

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  std::ifstream file(argv[1], std::ios::binary);
  uint32_t header[3];
  file.read(reinterpret_cast<char*>(header), sizeof(header));
  std::vector<uint8_t> infos(header[1] * 24);
  file.read(reinterpret_cast<char*>(infos.data()), infos.size());
  std::vector<uint8_t> encrypted(header[2]);
  file.read(reinterpret_cast<char*>(encrypted.data()), encrypted.size());
  uint8_t key[] = {0x51, 0xF3, 0x0F, 0x11, 0x04, 0x24, 0x6A, 0x00};
  kukdh1::CryptICE ice(key, 8);
  uint8_t* decrypted = nullptr;
  uint32_t length = 0;
  ice.decrypt(encrypted.data(), static_cast<uint32_t>(encrypted.size()), &decrypted, &length);
  std::cout.write(reinterpret_cast<char*>(decrypted), length);
  free(decrypted);
}
