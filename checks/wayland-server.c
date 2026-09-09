#include <stdlib.h>
#include <wayland-server.h>

static struct wl_display *display;

static void disconnected(struct wl_listener *listener, void *data) {
  (void)listener;
  (void)data;
  wl_display_terminate(display);
}

static void bind_compositor(struct wl_client *client, void *data, uint32_t version, uint32_t id) {
  (void)data;
  wl_resource_create(client, &wl_compositor_interface, version, id);
}

int main(int argc, char **argv) {
  if (argc != 2) return 1;
  display = wl_display_create();
  if (!display) return 1;
  if (!wl_global_create(display, &wl_compositor_interface, 1, NULL, bind_compositor)) return 1;
  struct wl_client *client = wl_client_create(display, atoi(argv[1]));
  if (!client) return 1;
  struct wl_listener listener = { .notify = disconnected };
  wl_client_add_destroy_listener(client, &listener);
  wl_display_run(display);
  wl_display_destroy(display);
  return 0;
}
