/* regional.c -- the European game's own cars, the Vauxhall Corsa and the
 * Peugeot 106, in this North American game.
 *
 * The game folder has both (CARS\CORSA, CARS\PEUGOT106: the same files as the
 * European release's) and CarTypeInfo lists them (types 7 and 6, among the 31
 * player cars, with their names in every language's text), but the North
 * American exe keeps them off its lists by the game's region ([0x864f24],
 * 0x570a30; 0 in this exe):
 *  - 0x5022c0, whether the region sells a car type, for the car lot
 *    (UICareerCarLot::BuildCarList, 0x4df9c0, at 0x4dfa83) and every other
 *    car select (UIQRCarSelect::BuildCarList, 0x4e22e0, at 0x4e2374: Quick
 *    Race, Customize, LAN, and Online's UI_OLCarSelect.fng, whose screen is
 *    made by the same 0x4fc190): no for a type in the region's table, region
 *    0's {7, 6} at 0x7f7c48, the others' {5, 18} (the Civic and the RSX) at
 *    0x7f7c50;
 *  - 0x4feaf0, the AI racers' cars: a random one rated near the player's car
 *    from the region's 26 types (region 0's at 0x7f6da4, the others' at
 *    0x7f6dc0 with 7 and 6 in place of 5 and 18; 3 SUVs at 0x7f6ddc when
 *    the player drives an SUV).
 * Here region 0's table holds no type (-1), and its AI list is 28 long, the
 * two in the padding after it (read by nothing else; HOOK_SITE 0x4febad,
 * where both lists' paths meet).  The same as NFSU2 Extra Options'
 * UnlockRegionalCars (ExOptsTeam/NFSU2ExOpts, ExtraOptionsStuff.h).  The
 * page's save check (web/src/app/profile.ts) has always counted both among
 * the game's cars. */
#include "cpu.h"
#include "widescreen.h"           /* HOOK_SITE */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "guest.h"

#define LOCKED_NA       0x007f7c48u   /* 2 car types region 0 does not sell */
#define AI_CARS_NA      0x007f6da4u   /* region 0's AI car types, a byte each */
#define AI_CARS_NA_N    26u
#define T_PEUGOT106     6u
#define T_CORSA         7u

static int g_on;

void regional_install(void){
    /* only on the data of the exe this port is made for */
    if (MR32(LOCKED_NA) != T_CORSA || MR32(LOCKED_NA + 4u) != T_PEUGOT106
        || MR8(AI_CARS_NA + AI_CARS_NA_N - 2u) != 5u || MR8(AI_CARS_NA + AI_CARS_NA_N - 1u) != 18u
        || MR16(AI_CARS_NA + AI_CARS_NA_N) != 0u){
        fprintf(stderr, "[cars] the exe's region tables are not the ones expected: no Corsa or 106\n");
        return;
    }
    MR32(LOCKED_NA) = MR32(LOCKED_NA + 4u) = 0xffffffffu;
    MR8(AI_CARS_NA + AI_CARS_NA_N) = T_CORSA;
    MR8(AI_CARS_NA + AI_CARS_NA_N + 1u) = T_PEUGOT106;
    g_on = 1;
}


/* GT4 dealership prototype, opt-in developer test only. The original list
 * builder stays in charge of creating the entries, their unlock status,
 * preview models and purchase behavior. This hook runs AFTER both native
 * eligibility tests at 0x4dfa83 and 0x4dfa95, before test al,al.
 * A first unfiltered list observes the requested brand. Subsequent builds
 * can filter only if it was offered in the preceding unfiltered/filtered
 * build. No other screens or the retail table are affected.
 */
extern uint32_t addon_cartype_count(void);
static char g_dealer_brand[33];
static unsigned g_dealer_seen, g_dealer_matches, g_dealer_hidden;
static int g_dealer_active, g_dealer_filter;
static uint32_t g_dealer_table, g_dealer_previous_db;

static const char *dealer_brand(const char *s){
    if (!strcasecmp(s,"PEUGOT")) return "PEUGEOT";
    if (!strcasecmp(s,"VW")) return "VOLKSWAGEN";
    if (!strcasecmp(s,"CORVETTE")) return "CHEVROLET";
    if (!strcasecmp(s,"OLDDODGE")) return "DODGE";
    return s;
}

void gt4_dealer_begin(uint32_t db, uint32_t filter){
    g_dealer_active = 0;
    if (filter != 1u || addon_cartype_count() != 58u) return;
    const char *requested = getenv("NFSU2_GT4_DEALER");
    if (!requested || !*requested || strlen(requested) > 32u) return;
    if (!strcasecmp(requested,"ALL")) requested = "";
    const char *brand = dealer_brand(requested);
    uint32_t table = guest_rd32(0x008a1cccu);
    if (!guest_ok_bytes(table,58u*0x890u)) return;
    g_dealer_filter = *brand && table == g_dealer_table && db == g_dealer_previous_db &&
                      !strcasecmp(brand,g_dealer_brand) && g_dealer_matches != 0u;
    snprintf(g_dealer_brand,sizeof g_dealer_brand,"%s",brand);
    g_dealer_table=table; g_dealer_previous_db=db;
    g_dealer_seen=g_dealer_matches=g_dealer_hidden=0;
    g_dealer_active=1;
    fprintf(stderr,"[gt4-dealer] build: %s; %s\n",*brand?brand:"ALL",
            g_dealer_filter?"filter enabled":"unfiltered availability pass");
}

void gt4_dealer_end(void){
    if (!g_dealer_active) return;
    fprintf(stderr,"[gt4-dealer] complete: eligible=%u matches=%u hidden=%u; %s\n",
            g_dealer_seen,g_dealer_matches,g_dealer_hidden,
            g_dealer_filter?"filtered":"unfiltered");
    g_dealer_active=0;
}

static void gt4_dealer_candidate(CPU *c){
    if (!g_dealer_active || !(c->eax & 0xffu)) return;
    uint32_t r=c->ebx;
    if (r<g_dealer_table || r-g_dealer_table>=58u*0x890u ||
        (r-g_dealer_table)%0x890u || !guest_ok_bytes(r,0x890u)) return;
    uint32_t t=(r-g_dealer_table)/0x890u;
    if (MR32(r+0x840u)!=t) return;
    char name[33], rawbrand[17];
    guest_read_str(r,name,sizeof name);
    guest_read_str(r+0xc0u,rawbrand,sizeof rawbrand);
    const char *brand=dealer_brand(rawbrand);
    int match=!*g_dealer_brand || !strcasecmp(brand,g_dealer_brand);
    g_dealer_seen++;
    if (match) g_dealer_matches++;
    if (!match && g_dealer_filter){
        c->eax &= ~0xffu;
        g_dealer_hidden++;
    }
    fprintf(stderr,"[gt4-dealer] type=%u car=%s brand=%s %s\n",t,name,brand,
            !match && g_dealer_filter?"hidden":"offered");
}

int regional_hook(CPU *c, uint32_t ip){
    if (ip == HOOK_SITE(0x004dfa9a)){ gt4_dealer_candidate(c); return 1; }
    if (ip != HOOK_SITE(0x004febad)) return 0;    /* mov eax, [esp+0x34]: esi the list, ebp its length */
    if (g_on && c->esi == AI_CARS_NA && c->ebp == AI_CARS_NA_N) c->ebp = AI_CARS_NA_N + 2u;
    return 1;
}
