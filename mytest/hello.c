#include <stdio.h>
#include <stdlib.h>

char* function() {
    char *a = malloc(256);
    scanf("%s", a);
    for (int i = 0; i < 257; i++) 
        a[i] = i;
    return a;
}

int main(int argc, char* argv[]) {
    printf("what the fuck %s", function());
}
