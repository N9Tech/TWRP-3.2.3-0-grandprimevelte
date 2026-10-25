#ifndef _MINCRYPT_SHA_H_
#define _MINCRYPT_SHA_H_
#include <stdint.h>
#define SHA_DIGEST_SIZE 20
typedef struct { uint32_t state[5]; uint64_t count; uint8_t buffer[64]; } SHA_CTX;
void SHA_init(SHA_CTX *ctx);
void SHA_update(SHA_CTX *ctx, const void *data, int len);
uint8_t* SHA_final(SHA_CTX *ctx);
#endif
