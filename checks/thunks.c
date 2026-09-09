#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <wayland-util.h>
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>

static int use_nix_paths;

static void *open_library(const char *name) {
  if (use_nix_paths) {
    for (size_t i = 0; i < sizeof(nix_libraries) / sizeof(nix_libraries[0]); ++i) {
      if (strcmp(name, nix_libraries[i].name) == 0) {
        name = nix_libraries[i].path;
        break;
      }
    }
  }
  void *handle = dlopen(name, RTLD_NOW | RTLD_GLOBAL);
  if (!handle) {
    fprintf(stderr, "%s: %s\n", name, dlerror());
    exit(1);
  }
  return handle;
}

static void *symbol(void *handle, const char *name) {
  void *address = dlsym(handle, name);
  if (!address) {
    fprintf(stderr, "%s: %s\n", name, dlerror());
    exit(1);
  }
  return address;
}

#define CHECK(condition) do { \
  if (!(condition)) { \
    fprintf(stderr, "line %d: %s failed\n", __LINE__, #condition); \
    exit(1); \
  } \
} while (0)

static void registry_global(void *data, void *registry, uint32_t name, const char *interface, uint32_t version) {
  (void)registry;
  (void)name;
  CHECK(version == 1);
  CHECK(strcmp(interface, "wl_compositor") == 0);
  *(int *)data = 1;
}

static void registry_remove(void *data, void *registry, uint32_t name) {
  (void)data;
  (void)registry;
  (void)name;
}

static void *(*mixer_callback_private)(void *);
static void *mixer_element;
static int mixer_events, mixer_freed;

static int mixer_callback(void *element, unsigned int mask) {
  CHECK(element == mixer_element);
  CHECK(mixer_callback_private(element) == &mixer_events);
  CHECK(mask == (mixer_events == 0 ? 1u : mixer_events == 1 ? 2u : ~0u));
  ++mixer_events;
  return 23;
}

static void mixer_private_free(void *element) {
  CHECK(element == mixer_element);
  ++mixer_freed;
}

static int mixer_compare(const void *a, const void *b) {
  CHECK(a == mixer_element && b == mixer_element);
  return 0;
}

static void check_mixer_callbacks(void *library) {
  int (*mixer_open)(void **, int) = symbol(library, "snd_mixer_open");
  int (*mixer_close)(void *) = symbol(library, "snd_mixer_close");
  int (*class_malloc)(void **) = symbol(library, "snd_mixer_class_malloc");
  int (*class_register)(void *, void *) = symbol(library, "snd_mixer_class_register");
  int (*class_set_compare)(void *, int (*)(const void *, const void *)) = symbol(library, "snd_mixer_class_set_compare");
  int (*elem_new)(void **, int, int, void *, void (*)(void *)) = symbol(library, "snd_mixer_elem_new");
  int (*elem_add)(void *, void *) = symbol(library, "snd_mixer_elem_add");
  int (*elem_value)(void *) = symbol(library, "snd_mixer_elem_value");
  int (*elem_info)(void *) = symbol(library, "snd_mixer_elem_info");
  int (*elem_remove)(void *) = symbol(library, "snd_mixer_elem_remove");
  void (*set_callback)(void *, int (*)(void *, unsigned int)) = symbol(library, "snd_mixer_elem_set_callback");
  void (*set_private)(void *, void *) = symbol(library, "snd_mixer_elem_set_callback_private");
  mixer_callback_private = symbol(library, "snd_mixer_elem_get_callback_private");
  void *mixer, *mixer_class;
  mixer_events = mixer_freed = 0;
  CHECK(mixer_open(&mixer, 0) == 0);
  CHECK(class_malloc(&mixer_class) == 0);
  CHECK(class_set_compare(mixer_class, mixer_compare) == 0);
  CHECK(class_register(mixer_class, mixer) == 0);
  CHECK(elem_new(&mixer_element, 0, 0, NULL, mixer_private_free) == 0);
  CHECK(elem_add(mixer_element, mixer_class) == 0);
  set_private(mixer_element, &mixer_events);
  set_callback(mixer_element, mixer_callback);
  CHECK(elem_value(mixer_element) == 23);
  set_callback(mixer_element, NULL);
  CHECK(elem_info(mixer_element) == 0 && mixer_events == 1);
  set_callback(mixer_element, mixer_callback);
  CHECK(elem_info(mixer_element) == 23);
  CHECK(elem_remove(mixer_element) == 23);
  CHECK(mixer_events == 3 && mixer_freed == 1);
  CHECK(mixer_close(mixer) == 0);
  puts("ALSA mixer callbacks passed");
}

static void check_wayland_utilities(void *library) {
  void (*list_init)(struct wl_list *) = symbol(library, "wl_list_init");
  void (*list_insert)(struct wl_list *, struct wl_list *) = symbol(library, "wl_list_insert");
  void (*list_remove)(struct wl_list *) = symbol(library, "wl_list_remove");
  int (*list_length)(const struct wl_list *) = symbol(library, "wl_list_length");
  struct wl_list list, item;
  list_init(&list);
  list_insert(&list, &item);
  CHECK(list_length(&list) == 1 && item.prev == &list && item.next == &list);
  list_remove(&item);
  CHECK(list_length(&list) == 0);

  void (*array_init)(struct wl_array *) = symbol(library, "wl_array_init");
  void *(*array_add)(struct wl_array *, size_t) = symbol(library, "wl_array_add");
  int (*array_copy)(struct wl_array *, struct wl_array *) = symbol(library, "wl_array_copy");
  void (*array_release)(struct wl_array *) = symbol(library, "wl_array_release");
  struct wl_array array, copy;
  array_init(&array);
  array_init(&copy);
  uint32_t *value = array_add(&array, sizeof(*value));
  CHECK(value);
  *value = 0x12345678;
  CHECK(array_copy(&copy, &array) == 0);
  CHECK(copy.size == sizeof(*value) && *(uint32_t *)copy.data == *value);
  array_release(&copy);
  array_release(&array);
}

int main(int argc, char **argv) {
  setbuf(stdout, NULL);
  if (argc > 2 || (argc == 2 && strcmp(argv[1], "--nix-paths") != 0)) return 2;
  use_nix_paths = argc == 2;
  puts(use_nix_paths ? "Library paths: Nix store" : "Library paths: FHS SONAMEs");
  const char *icds = getenv("VK_DRIVER_FILES");
  CHECK(icds && strstr(icds, ".x86_64.json") && strstr(icds, ".i686.json"));
  CHECK(!strstr(icds, ".aarch64."));
  /* Avoid connecting to a desktop; exercise Mesa's surfaceless EGL path. */
  unsetenv("DISPLAY");
  unsetenv("WAYLAND_DISPLAY");
  setenv("EGL_PLATFORM", "surfaceless", 1);

  struct timespec now;
  CHECK(clock_gettime(CLOCK_MONOTONIC, &now) == 0);

  /* Reopening after other libraries reuse address space catches stale FEX
     procedure mappings and guest C++ finalization problems. */
  for (int i = 0; i < 3; ++i) {
    printf("%zu-bit iteration %d: GL/EGL\n", sizeof(void *) * 8, i + 1);
    void *gl = open_library("libGL.so.1");
    unsigned (*glGetError)(void) = symbol(gl, "glGetError");
    const unsigned char *(*glGetString)(unsigned) = symbol(gl, "glGetString");
    CHECK(glGetError() == 0);

    void *egl = open_library("libEGL.so.1");
    void *(*eglGetProcAddress)(const char *) = symbol(egl, "eglGetProcAddress");
    void *(*eglGetDisplay)(void *) = symbol(egl, "eglGetDisplay");
    void *(*eglGetPlatformDisplay)(unsigned, void *, const intptr_t *) = symbol(egl, "eglGetPlatformDisplay");
    const char *(*eglQueryString)(void *, int) = symbol(egl, "eglQueryString");
    unsigned (*eglInitialize)(void *, int *, int *) = symbol(egl, "eglInitialize");
    unsigned (*eglBindAPI)(unsigned) = symbol(egl, "eglBindAPI");
    unsigned (*eglChooseConfig)(void *, const int *, void **, int, int *) = symbol(egl, "eglChooseConfig");
    unsigned (*eglGetConfigs)(void *, void **, int, int *) = symbol(egl, "eglGetConfigs");
    void *(*eglCreateContext)(void *, void *, void *, const int *) = symbol(egl, "eglCreateContext");
    unsigned (*eglMakeCurrent)(void *, void *, void *, void *) = symbol(egl, "eglMakeCurrent");
    unsigned (*eglDestroyContext)(void *, void *) = symbol(egl, "eglDestroyContext");
    unsigned (*eglTerminate)(void *) = symbol(egl, "eglTerminate");
    unsigned (*eglGetConfigAttrib)(void *, void *, int, int *) = symbol(egl, "eglGetConfigAttrib");
    void *(*eglCreatePbufferSurface)(void *, void *, const int *) = symbol(egl, "eglCreatePbufferSurface");
    unsigned (*eglDestroySurface)(void *, void *) = symbol(egl, "eglDestroySurface");
    void *(*eglCreateSync)(void *, unsigned, const intptr_t *) = symbol(egl, "eglCreateSync");
    unsigned (*eglDestroySync)(void *, void *) = symbol(egl, "eglDestroySync");
    CHECK(eglGetProcAddress("eglQueryString") == (void *)eglQueryString);
    CHECK(eglGetProcAddress("eglGetProcAddress") == (void *)eglGetProcAddress);
    CHECK(!eglGetProcAddress("eglSteamAsahiNonexistentExtension"));
    const intptr_t platform_attributes[] = {0x3038};
    void *display = i == 0 ? eglGetDisplay(NULL)
                          : eglGetPlatformDisplay(0x31DD, NULL, platform_attributes);
    CHECK(display);
    int major, minor, count;
    CHECK(eglInitialize(display, &major, &minor));
    CHECK(eglQueryString(display, 0x3053)); /* EGL_VENDOR */
    const int gles = i == 2;
    CHECK(eglBindAPI(gles ? 0x30A0 : 0x30A2)); /* GLES or OpenGL */
    const int attributes[] = {0x3040, gles ? 0x0040 : 0x0008, 0x3033, 0x0001, 0x3038};
    struct { void *configs[4]; uintptr_t guard; } configs = {{0}, 0x12345678};
    CHECK(eglGetConfigs(display, configs.configs, 4, &count));
    CHECK(count >= 2 && count <= 4 && configs.guard == 0x12345678);
    for (int j = 0; j < count; j++) {
      int id;
      CHECK(eglGetConfigAttrib(display, configs.configs[j], 0x3028, &id));
    }
    CHECK(eglChooseConfig(display, attributes, configs.configs, 4, &count));
    CHECK(count >= 2 && count <= 4 && configs.guard == 0x12345678);
    void *config = configs.configs[0];
    const int context_attributes[] = {gles ? 0x3098 : 0x3038, 3, 0x3038};
    void *context = eglCreateContext(display, config, NULL, context_attributes);
    CHECK(context);
    const int surface_attributes[] = {0x3057, 16, 0x3056, 16, 0x3038};
    void *surface = eglCreatePbufferSurface(display, config, surface_attributes);
    CHECK(surface);
    CHECK(eglMakeCurrent(display, surface, surface, context));
    const unsigned char *renderer = glGetString(0x1F01); /* GL_RENDERER */
    CHECK(renderer);
    printf("EGL %d.%d, GL renderer: %s\n", major, minor, renderer);
    CHECK(glGetError() == 0);
    unsigned (*create_program)(void) = symbol(gl, "glCreateProgram");
    void (*delete_program)(unsigned) = symbol(gl, "glDeleteProgram");
    void (*feedback_varyings)(unsigned, int, const char *const *, unsigned) = symbol(gl, "glTransformFeedbackVaryings");
    unsigned program = create_program();
    CHECK(program);
    const char *varyings[] = {"first", "second"};
    feedback_varyings(program, 2, varyings, 0x8C8C); /* GL_INTERLEAVED_ATTRIBS */
    CHECK(glGetError() == 0);
    feedback_varyings = eglGetProcAddress("glTransformFeedbackVaryings");
    CHECK(feedback_varyings);
    feedback_varyings(program, 2, varyings, 0x8C8C);
    CHECK(glGetError() == 0);
    delete_program(program);
    /* EGL users commonly load GLVND's split OpenGL/GLES libraries. They must
       use the same native dispatch state as the context created above. */
    const char *client_libraries[] = {"libOpenGL.so.0", "libGLESv2.so.2"};
    for (unsigned j = 0; j < sizeof(client_libraries) / sizeof(*client_libraries); ++j) {
      void *client = open_library(client_libraries[j]);
      const unsigned char *(*get_string)(unsigned) = symbol(client, "glGetString");
      CHECK(get_string(0x1F01));
      CHECK(dlclose(client) == 0);
    }
    if (gles) {
      void (*blend_barrier)(void) = eglGetProcAddress("glBlendBarrier");
      void (*bounding_box)(float, float, float, float, float, float, float, float) = eglGetProcAddress("glPrimitiveBoundingBox");
      CHECK(blend_barrier && bounding_box);
      blend_barrier();
      bounding_box(-1, -1, -1, 1, 1, 1, 1, 1);
      CHECK(glGetError() == 0);
    }
    const intptr_t sync_attributes[] = {0x3038};
    void *sync = eglCreateSync(display, 0x30F9, sync_attributes); /* EGL_SYNC_FENCE */
    CHECK(sync);
    unsigned (*eglGetSyncAttrib)(void *, void *, int, intptr_t *) = symbol(egl, "eglGetSyncAttrib");
    struct { intptr_t value; uintptr_t guard; } sync_type = {0, 0x12345678};
    CHECK(eglGetSyncAttrib(display, sync, 0x30F7, &sync_type.value)); /* EGL_SYNC_TYPE */
    CHECK(sync_type.value == 0x30F9 && sync_type.guard == 0x12345678);
    CHECK(eglDestroySync(display, sync));
    CHECK(eglMakeCurrent(display, NULL, NULL, NULL));
    CHECK(eglDestroySurface(display, surface));
    CHECK(eglDestroyContext(display, context));
    CHECK(eglTerminate(display));
    CHECK(dlclose(egl) == 0);
    CHECK(dlclose(gl) == 0);

    puts("Wayland");
    void *wl = open_library("libwayland-client.so.0");
    check_wayland_utilities(wl);
    void *(*wl_display_connect)(const char *) = symbol(wl, "wl_display_connect");
    CHECK(!wl_display_connect("/nonexistent-x86-on-arm-test-display"));
    void *(*wl_display_connect_to_fd)(int) = symbol(wl, "wl_display_connect_to_fd");
    int (*wl_display_roundtrip_queue)(void *, void *) = symbol(wl, "wl_display_roundtrip_queue");
    void *(*wl_display_create_queue_with_name)(void *, const char *) = symbol(wl, "wl_display_create_queue_with_name");
    const char *(*wl_event_queue_get_name)(void *) = symbol(wl, "wl_event_queue_get_name");
    void (*wl_event_queue_destroy)(void *) = symbol(wl, "wl_event_queue_destroy");
    void (*wl_proxy_set_queue)(void *, void *) = symbol(wl, "wl_proxy_set_queue");
    void *(*wl_proxy_get_queue)(void *) = symbol(wl, "wl_proxy_get_queue");
    void *(*wl_proxy_get_display)(void *) = symbol(wl, "wl_proxy_get_display");
    int (*wl_display_dispatch_queue_timeout)(void *, void *, const struct timespec *) = symbol(wl, "wl_display_dispatch_queue_timeout");
    void (*wl_display_disconnect)(void *) = symbol(wl, "wl_display_disconnect");
    void *(*wl_proxy_marshal_flags)(void *, uint32_t, const void *, uint32_t, uint32_t, ...) = symbol(wl, "wl_proxy_marshal_flags");
    int (*wl_proxy_add_listener)(void *, void (**)(void), void *) = symbol(wl, "wl_proxy_add_listener");
    void (*wl_proxy_destroy)(void *) = symbol(wl, "wl_proxy_destroy");
    int sockets[2];
    CHECK(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    pid_t server = fork();
    CHECK(server >= 0);
    if (server == 0) {
      close(sockets[0]);
      char fd[32];
      snprintf(fd, sizeof(fd), "%d", sockets[1]);
      execl(WAYLAND_SERVER, WAYLAND_SERVER, fd, (char *)NULL);
      _exit(127);
    }
    close(sockets[1]);
    alarm(10);
    void *wl_display = wl_display_connect_to_fd(sockets[0]);
    CHECK(wl_display);
    void *registry = wl_proxy_marshal_flags(wl_display, 1, symbol(wl, "wl_registry_interface"), 1, 0, NULL);
    CHECK(registry);
    const struct wl_interface *(*wl_proxy_get_interface)(void *) = symbol(wl, "wl_proxy_get_interface");
    CHECK(wl_proxy_get_interface(registry) == symbol(wl, "wl_registry_interface"));
    void *queue = wl_display_create_queue_with_name(wl_display, "thunk-smoke");
    CHECK(queue && strcmp(wl_event_queue_get_name(queue), "thunk-smoke") == 0);
    wl_proxy_set_queue(registry, queue);
    CHECK(wl_proxy_get_queue(registry) == queue);
    CHECK(wl_proxy_get_display(registry) == wl_display);
    void (*listener[])(void) = {(void (*)(void))registry_global, (void (*)(void))registry_remove};
    int seen_global = 0;
    CHECK(wl_proxy_add_listener(registry, listener, &seen_global) == 0);
    CHECK(wl_display_roundtrip_queue(wl_display, queue) >= 0);
    CHECK(seen_global);
    struct { struct timespec timeout; uint32_t guard; } timed = {{0, 1000000}, 0x12345678};
    CHECK(wl_display_dispatch_queue_timeout(wl_display, queue, &timed.timeout) == 0);
    CHECK(timed.guard == 0x12345678);
    wl_proxy_destroy(registry);
    wl_event_queue_destroy(queue);
    wl_display_disconnect(wl_display);
    int server_status;
    CHECK(waitpid(server, &server_status, 0) == server);
    CHECK(WIFEXITED(server_status) && WEXITSTATUS(server_status) == 0);
    alarm(0);
    CHECK(dlclose(wl) == 0);

    /* FEX 2609 supplies these thunks only for x86-64. On i386, also verify
       that preserving the rootfs's x86 loaders leaves the fallback usable. */
    puts("ALSA/DRM");
    void *alsa = open_library("libasound.so.2");
    const char *(*snd_asoundlib_version)(void) = symbol(alsa, "snd_asoundlib_version");
    int (*snd_pcm_open)(void **, const char *, int, int) = symbol(alsa, "snd_pcm_open");
    int (*snd_pcm_close)(void *) = symbol(alsa, "snd_pcm_close");
    printf("ALSA %s\n", snd_asoundlib_version());
    void *pcm;
    CHECK(snd_pcm_open(&pcm, "null", 0, 0) == 0);
    CHECK(snd_pcm_close(pcm) == 0);
    CHECK(snd_pcm_open(&pcm, "default", 0, 0) == 0);
    CHECK(snd_pcm_close(pcm) == 0);
    puts("Default ALSA PCM connected");
    check_mixer_callbacks(alsa);
    CHECK(dlclose(alsa) == 0);
    void *drm = open_library("libdrm.so.2");
    int (*drmAvailable)(void) = symbol(drm, "drmAvailable");
    CHECK(drmAvailable());
    CHECK(dlclose(drm) == 0);

    puts("Vulkan");
    void *vulkan = open_library("libvulkan.so.1");
    PFN_vkCreateInstance create_instance = symbol(vulkan, "vkCreateInstance");
    PFN_vkDestroyInstance destroy_instance = symbol(vulkan, "vkDestroyInstance");
    PFN_vkEnumeratePhysicalDevices enumerate_devices = symbol(vulkan, "vkEnumeratePhysicalDevices");
    PFN_vkGetPhysicalDeviceProperties get_properties = symbol(vulkan, "vkGetPhysicalDeviceProperties");
    const VkApplicationInfo app = {
      .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1
    };
    const VkInstanceCreateInfo info = {
      .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app
    };
    VkInstance instance;
    CHECK(create_instance(&info, NULL, &instance) == VK_SUCCESS);
    uint32_t num_devices = 0;
    CHECK(enumerate_devices(instance, &num_devices, NULL) == VK_SUCCESS);
    CHECK(num_devices > 0);
    VkPhysicalDevice *devices = calloc(num_devices, sizeof(*devices));
    CHECK(devices);
    CHECK(enumerate_devices(instance, &num_devices, devices) == VK_SUCCESS);
    for (uint32_t j = 0; j < num_devices; ++j) {
      VkPhysicalDeviceProperties properties;
      get_properties(devices[j], &properties);
      printf("Vulkan device: %s\n", properties.deviceName);
    }
    free(devices);
    destroy_instance(instance, NULL);
    CHECK(dlclose(vulkan) == 0);
  }
  puts("Guest thunk smoke tests: PASS");
  return 0;
}
