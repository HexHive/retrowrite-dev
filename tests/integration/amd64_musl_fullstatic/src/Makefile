
CC=x86_64-linux-musl-gcc
#CC=aarch64-linux-musl-gcc

default: hellostatic hellostatic.fullrelro

hellostatic: hello.c
	$(CC) -static -Bstatic -pie -fPIE -fPIC -o hellostatic hello.c

hellostatic.fullrelro: hello.c
	$(CC) -Wl,-z,relro,-z,now -static -Bstatic -pie -fPIE -fPIC -o hellostatic.fullrelro hello.c

clean:
	rm -f hellostatic hellostatic.fullrelro
